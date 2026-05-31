"""MCP server runtime."""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from peplink_core.bootstrap import load_runtime_fleet
from peplink_core.discovery import discover_lan_clients, discover_mesh_peers, discover_synergy_peers
from peplink_core.doctor import run_doctor
from peplink_core.endpoints.cmd import get_ap_cmd_support, summarize_ap_cmd_support
from peplink_core.endpoints.config import (
    get_admin_config,
    get_dhcp_config,
    get_dns_config,
    get_firewall_config,
    get_gpio_config,
    get_incontrol_config,
    get_lan_config,
    get_mesh_config,
    get_nat_mapping_config,
    get_pepvpn_config,
    get_pepvpn_profile_config,
    get_port_config,
    get_schedule_config,
    get_snmp_info_config,
    get_ssid_profile_config,
    get_wan_config,
    get_wan_connection_config,
    get_wan_connection_priority_config,
    summarize_admin_config,
    summarize_dhcp_config,
    summarize_dns_config,
    summarize_firewall_config,
    summarize_gpio_config,
    summarize_incontrol_config,
    summarize_lan_config,
    summarize_nat_mapping_config,
    summarize_pepvpn_config,
    summarize_pepvpn_profile_config,
    summarize_port_config,
    summarize_schedule_config,
    summarize_snmp_info_config,
    summarize_ssid_profiles,
    summarize_wan_config,
    summarize_wan_connection_config,
    summarize_wan_connection_priority_config,
)
from peplink_core.endpoints.info import (
    get_firmware,
    get_location,
    summarize_firmware,
    summarize_location,
)
from peplink_core.endpoints.status import (
    get_bandwidth_usage_client,
    get_clients,
    get_cpu_status,
    get_extap_mesh,
    get_extap_mesh_link,
    get_lan_profile,
    get_lan_status,
    get_pepvpn,
    get_port_status,
    get_status_log,
    get_traffic,
    get_wan_connection,
    get_wan_connection_allowance,
    get_wan_latency,
    get_wan_status,
    summarize_bandwidth_usage_client,
    summarize_clients,
    summarize_cpu_status,
    summarize_lan_profile,
    summarize_lan_status,
    summarize_pepvpn,
    summarize_port_status,
    summarize_status_log,
    summarize_traffic,
    summarize_wan_connection,
    summarize_wan_latency,
    summarize_wan_status,
)
from peplink_core.exceptions import PeplinkConfigError
from peplink_core.management import management_gateway_id, resolve_config_port_read_handle
from peplink_core.registry import DeviceRegistry
from peplink_core.snmp.ap import (
    ap_device_status_as_info_firmware,
    fetch_ap_device_status,
    fetch_ap_lan_profile,
    fetch_ap_ssid_profile_config,
    fetch_ap_wlan_clients,
    fetch_ap_wlan_summary,
)
from peplink_mcp_shared.context import AppContext
from peplink_mcp_shared.mcp_keys import McpKeyStore
from peplink_mcp_shared.policy import PolicyGate

from peplink_device_mcp.ic2_tools import register_ic2_tools
from peplink_device_mcp.manifest_tools import register_manifest_tools

logger = logging.getLogger(__name__)


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def create_server(
    *,
    config_path: str | None = None,
    secrets_path: str | None = None,
    stateless_http: bool = False,
) -> tuple[FastMCP, AppContext]:
    fleet = load_runtime_fleet(config_path, secrets_path)
    ctx = AppContext(
        fleet=fleet,
        registry=DeviceRegistry(fleet),
        key_store=McpKeyStore.from_fleet(fleet),
        policy=PolicyGate.from_env(),
    )
    if ctx.policy.allowed:
        logger.info("Policy flags enabled: %s", ", ".join(sorted(ctx.policy.allowed)))
    caps = ctx.capabilities()

    if caps["admin_tools_enabled"]:
        instructions = (
            "Peplink direct device API. Read tools always available; write/config/cmd POST tools "
            "register when auth.admin is configured on at least one device. Destructive manifest "
            "tools (reboot, config apply, SMS, WAN changes) require admin MCP tier. "
            "Wildly experimental — verify before invoking writes."
        )
    else:
        instructions = (
            "Peplink direct device API in read-only mode. Only read-only tools are "
            "registered; admin credentials were not configured so manifest POST/write "
            "tools are omitted. Device IPs for discover.* entries are resolved from the "
            "gateway at startup."
        )

    if fleet.ic2_enabled:
        instructions += (
            " InControl 2 cloud tools (peplink_ic2_*) are enabled: use them for fleet "
            "inventory/status via the cloud and for InControl-managed config changes "
            "(SSID, VLAN, WAN priority, firewall, etc.). Device-config changes that belong "
            "to InControl should be routed through the peplink_ic2_* tools, not the LAN API."
        )

    server = FastMCP("peplink-device", instructions=instructions, stateless_http=stateless_http)

    @server.tool(name="peplink_whoami")
    def peplink_whoami() -> str:
        """Show the authenticated MCP caller (key id + tier) and what it may do.

        Over HTTP the tier comes from the bearer key; over stdio it comes from
        PEPLINK_MCP_KEY / PEPLINK_MCP_TIER. Unauthenticated callers report null.
        """
        principal = ctx.current_principal()
        return _json(
            {
                "authenticated": principal is not None,
                "key_id": principal.key_id if principal else None,
                "tier": principal.tier if principal else None,
                "source": principal.source if principal else None,
                "can_call_admin_tools": bool(principal and principal.allows("admin")),
                "mcp_keys_configured": ctx.key_store.key_count,
            }
        )

    @server.tool(name="peplink_list_devices")
    def peplink_list_devices() -> str:
        """List configured Peplink devices and auth types (no secrets returned).

        Pass device_id to other tools to target a specific host. When omitted,
        defaults.device_id from config.yaml is used.
        """
        return _json({"capabilities": caps, "devices": ctx.list_devices()})

    @server.tool(name="peplink_discover_mesh_devices")
    def peplink_discover_mesh_devices(gateway_id: str | None = None) -> str:
        """List AP/mesh peers visible to a gateway (read-only mesh status APIs)."""
        did, _ = ctx.fleet.get_device(gateway_id or ctx.fleet.defaults.gateway_id)
        handle = ctx.resolve_device(did)
        peers = discover_mesh_peers(handle.read_only)
        return _json(
            {
                "gateway_id": did,
                "gateway_host": handle.config.host,
                "peer_count": len(peers),
                "peers": [
                    {
                        "name": p.name,
                        "host": p.host,
                        "mac": p.mac,
                        "model": p.model,
                        "mesh_id": p.mesh_id,
                        "kind_hint": p.kind_hint,
                        "source": p.source,
                    }
                    for p in peers
                ],
            }
        )

    @server.tool(name="peplink_discover_lan_clients")
    def peplink_discover_lan_clients(gateway_id: str | None = None) -> str:
        """List LAN clients on a gateway (useful for AP discovery via client_type)."""
        did, _ = ctx.fleet.get_device(gateway_id or ctx.fleet.defaults.gateway_id)
        handle = ctx.resolve_device(did)
        clients = discover_lan_clients(handle.read_only)
        return _json(
            {
                "gateway_id": did,
                "gateway_host": handle.config.host,
                "client_count": len(clients),
                "clients": [
                    {
                        "name": c.name,
                        "host": c.host,
                        "mac": c.mac,
                        "model": c.model,
                        "client_type": c.model,
                        "source": c.source,
                    }
                    for c in clients
                ],
            }
        )

    @server.tool(name="peplink_discover_synergy_devices")
    def peplink_discover_synergy_devices(gateway_id: str | None = None) -> str:
        """List synergized router serials on a Synergy Controller (WAN status API)."""
        did, _ = ctx.fleet.get_device(gateway_id or ctx.fleet.defaults.gateway_id)
        handle = ctx.resolve_device(did)
        gw_host = handle.config.host or ""
        peers = discover_synergy_peers(handle.read_only, gateway_host=gw_host)
        return _json(
            {
                "gateway_id": did,
                "gateway_host": gw_host,
                "peer_count": len(peers),
                "peers": [
                    {
                        "name": p.name,
                        "host": p.host,
                        "kind_hint": p.kind_hint,
                        "source": p.source,
                    }
                    for p in peers
                ],
            }
        )

    @server.tool(name="peplink_get_status_wan_connection")
    def peplink_get_status_wan_connection(
        device_id: str | None = None,
        lite: bool = True,
    ) -> str:
        """Get WAN connection status for a device (read-only)."""
        handle = ctx.resolve_device(device_id)
        data = get_wan_connection(handle.read_only, lite=lite)
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_wan_connection(data),
            }
        )

    @server.tool(name="peplink_get_info_location")
    def peplink_get_info_location(device_id: str | None = None) -> str:
        """Get GPS / location fix from the device (read-only)."""
        handle = ctx.resolve_device(device_id)
        data = get_location(handle.read_only)
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_location(data),
            }
        )

    @server.tool(name="peplink_get_info_firmware")
    def peplink_get_info_firmware(device_id: str | None = None) -> str:
        """Get firmware versions installed on the device (read-only)."""
        did, device = ctx.fleet.get_device(device_id)
        if device.kind == "ap":
            did, device = ctx.resolve_ap_snmp(device_id)
            assert device.snmp is not None and device.host
            status = fetch_ap_device_status(device.host, device.snmp)
            data = ap_device_status_as_info_firmware(status)
            return _json(
                {
                    "device_id": did,
                    "host": device.host,
                    "transport": "snmp",
                    **summarize_firmware(data),
                }
            )
        handle = ctx.resolve_device(device_id)
        data = get_firmware(handle.read_only)
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                "transport": "http",
                **summarize_firmware(data),
            }
        )

    @server.tool(name="peplink_get_status_pepvpn")
    def peplink_get_status_pepvpn(device_id: str | None = None) -> str:
        """Get PepVPN / SpeedFusion profile status and live peers (read-only)."""
        handle = ctx.resolve_device(device_id)
        data = get_pepvpn(handle.read_only)
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_pepvpn(data),
            }
        )

    @server.tool(name="peplink_get_config_pepvpn")
    def peplink_get_config_pepvpn(device_id: str | None = None) -> str:
        """Get PepVPN site settings (GET /api/config.pepvpn; FusionHub + some routers)."""
        handle = ctx.resolve_device(device_id)
        data = get_pepvpn_config(handle.read_client_for_path("/api/config.pepvpn"))
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_pepvpn_config(data),
            }
        )

    @server.tool(name="peplink_get_config_pepvpn_profile")
    def peplink_get_config_pepvpn_profile(device_id: str | None = None) -> str:
        """Get PepVPN profile config (GET /api/config.pepvpn.profile; PSKs redacted)."""
        handle = ctx.resolve_device(device_id)
        data = get_pepvpn_profile_config(handle.read_client_for_path("/api/config.pepvpn.profile"))
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_pepvpn_profile_config(data),
            }
        )

    @server.tool(name="peplink_get_status_client")
    def peplink_get_status_client(
        device_id: str | None = None,
        active_only: bool = True,
        limit: int = 50,
    ) -> str:
        """List connected clients on the device (read-only, truncated by default)."""
        did, device = ctx.fleet.get_device(device_id)
        if device.kind == "ap":
            did, device = ctx.resolve_ap_snmp(device_id)
            assert device.snmp is not None and device.host
            data = fetch_ap_wlan_clients(device.host, device.snmp)
            clients = data.get("clients", [])[:limit]
            return _json(
                {
                    "device_id": did,
                    "host": device.host,
                    "transport": "snmp",
                    "total_reported": data.get("client_count", len(clients)),
                    "returned": len(clients),
                    "truncated": data.get("client_count", 0) > limit,
                    "clients": clients,
                }
            )
        handle = ctx.resolve_device(device_id)
        data = get_clients(handle.read_only, active_only=active_only)
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                "transport": "http",
                **summarize_clients(data, limit=limit),
            }
        )

    @server.tool(name="peplink_get_status_lan_profile")
    def peplink_get_status_lan_profile(device_id: str | None = None) -> str:
        """Get LAN profile status (read-only)."""
        did, device = ctx.fleet.get_device(device_id)
        if device.kind == "ap":
            did, device = ctx.resolve_ap_snmp(device_id)
            assert device.snmp is not None and device.host
            data = fetch_ap_lan_profile(device.host, device.snmp)
            return _json(
                {
                    "device_id": did,
                    "host": device.host,
                    "transport": "snmp",
                    **summarize_lan_profile(data),
                }
            )
        handle = ctx.resolve_device(device_id)
        data = get_lan_profile(handle.read_only)
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                "transport": "http",
                **summarize_lan_profile(data),
            }
        )

    @server.tool(name="peplink_get_status_wan_connection_allowance")
    def peplink_get_status_wan_connection_allowance(device_id: str | None = None) -> str:
        """Get WAN data allowance status (read-only)."""
        handle = ctx.resolve_device(device_id)
        data = get_wan_connection_allowance(handle.read_only)
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                "allowance": data,
            }
        )

    @server.tool(name="peplink_supplemental_get_status_traffic")
    def peplink_supplemental_get_status_traffic(device_id: str | None = None) -> str:
        """Get WAN traffic/bandwidth stats (GET /api/status.traffic, live-confirmed)."""
        handle = ctx.resolve_device(device_id)
        data = get_traffic(handle.read_only)
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_traffic(data),
            }
        )

    @server.tool(name="peplink_supplemental_get_status_log")
    def peplink_supplemental_get_status_log(
        device_id: str | None = None,
        limit: int = 20,
    ) -> str:
        """Get device event log lines (GET /api/status.log)."""
        handle = ctx.resolve_device(device_id)
        data = get_status_log(handle.read_only)
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_status_log(data, limit=limit),
            }
        )

    @server.tool(name="peplink_supplemental_get_status_wan_latency")
    def peplink_supplemental_get_status_wan_latency(device_id: str | None = None) -> str:
        """Get health-check latency per WAN (GET /api/status.wan.latency)."""
        handle = ctx.resolve_device(device_id)
        data = get_wan_latency(handle.read_only)
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_wan_latency(data),
            }
        )

    @server.tool(name="peplink_supplemental_get_status_bandwidth_usage_client")
    def peplink_supplemental_get_status_bandwidth_usage_client(
        device_id: str | None = None,
    ) -> str:
        """Get client bandwidth usage periods (GET /api/status.bandwidthUsage.client)."""
        handle = ctx.resolve_device(device_id)
        data = get_bandwidth_usage_client(handle.read_only)
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_bandwidth_usage_client(data),
            }
        )

    @server.tool(name="peplink_supplemental_get_config_admin")
    def peplink_supplemental_get_config_admin(device_id: str | None = None) -> str:
        """Get admin/system settings (GET /api/config.admin; needs config_read on gateway)."""
        handle = ctx.resolve_device(device_id)
        data = get_admin_config(handle.read_client_for_path("/api/config.admin"))
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_admin_config(data),
            }
        )

    @server.tool(name="peplink_supplemental_get_config_incontrol")
    def peplink_supplemental_get_config_incontrol(device_id: str | None = None) -> str:
        """Get InControl cloud settings (GET /api/config.incontrol)."""
        handle = ctx.resolve_device(device_id)
        data = get_incontrol_config(handle.read_client_for_path("/api/config.incontrol"))
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_incontrol_config(data),
            }
        )

    @server.tool(name="peplink_supplemental_get_config_lan")
    def peplink_supplemental_get_config_lan(device_id: str | None = None) -> str:
        """Get LAN/VLAN config (GET /api/config.lan)."""
        handle = ctx.resolve_device(device_id)
        data = get_lan_config(handle.read_client_for_path("/api/config.lan"))
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_lan_config(data),
            }
        )

    @server.tool(name="peplink_supplemental_get_config_snmp_info")
    def peplink_supplemental_get_config_snmp_info(device_id: str | None = None) -> str:
        """Get SNMP service settings (GET /api/config.snmp.info)."""
        handle = ctx.resolve_device(device_id)
        data = get_snmp_info_config(handle.read_client_for_path("/api/config.snmp.info"))
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_snmp_info_config(data),
            }
        )

    @server.tool(name="peplink_supplemental_get_config_firewall")
    def peplink_supplemental_get_config_firewall(device_id: str | None = None) -> str:
        """Get firewall policy config (GET /api/config.firewall)."""
        handle = ctx.resolve_device(device_id)
        data = get_firewall_config(handle.read_client_for_path("/api/config.firewall"))
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_firewall_config(data),
            }
        )

    @server.tool(name="peplink_supplemental_get_config_nat_mapping")
    def peplink_supplemental_get_config_nat_mapping(device_id: str | None = None) -> str:
        """Get NAT mapping config (GET /api/config.natMapping)."""
        handle = ctx.resolve_device(device_id)
        data = get_nat_mapping_config(handle.read_client_for_path("/api/config.natMapping"))
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_nat_mapping_config(data),
            }
        )

    @server.tool(name="peplink_supplemental_get_config_dhcp")
    def peplink_supplemental_get_config_dhcp(device_id: str | None = None) -> str:
        """Get DHCP service config (GET /api/config.dhcp)."""
        handle = ctx.resolve_device(device_id)
        data = get_dhcp_config(handle.read_client_for_path("/api/config.dhcp"))
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_dhcp_config(data),
            }
        )

    @server.tool(name="peplink_supplemental_get_config_dns")
    def peplink_supplemental_get_config_dns(device_id: str | None = None) -> str:
        """Get DNS proxy config (GET /api/config.dns)."""
        handle = ctx.resolve_device(device_id)
        data = get_dns_config(handle.read_client_for_path("/api/config.dns"))
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_dns_config(data),
            }
        )

    @server.tool(name="peplink_supplemental_get_config_schedule")
    def peplink_supplemental_get_config_schedule(device_id: str | None = None) -> str:
        """Get schedule rules config (GET /api/config.schedule)."""
        handle = ctx.resolve_device(device_id)
        data = get_schedule_config(handle.read_client_for_path("/api/config.schedule"))
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_schedule_config(data),
            }
        )

    @server.tool(name="peplink_supplemental_get_config_wan")
    def peplink_supplemental_get_config_wan(device_id: str | None = None) -> str:
        """Get WAN profile config shell (GET /api/config.wan — distinct from config.wan.connection)."""
        handle = ctx.resolve_device(device_id)
        data = get_wan_config(handle.read_client_for_path("/api/config.wan"))
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_wan_config(data),
            }
        )

    @server.tool(name="peplink_get_config_gpio")
    def peplink_get_config_gpio(device_id: str | None = None) -> str:
        """Get GPIO config (GET /api/config.gpio)."""
        handle = ctx.resolve_device(device_id)
        data = get_gpio_config(handle.read_client_for_path("/api/config.gpio"))
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_gpio_config(data),
            }
        )

    @server.tool(name="peplink_get_config_wan_connection_priority")
    def peplink_get_config_wan_connection_priority(device_id: str | None = None) -> str:
        """Get WAN connection priority groups (GET /api/config.wan.connection.priority)."""
        handle = ctx.resolve_device(device_id)
        data = get_wan_connection_priority_config(
            handle.read_client_for_path("/api/config.wan.connection.priority")
        )
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_wan_connection_priority_config(data),
            }
        )

    @server.tool(name="peplink_supplemental_get_status_wan")
    def peplink_supplemental_get_status_wan(device_id: str | None = None) -> str:
        """Get WAN status summary (GET /api/status.wan — shorter path than status.wan.connection)."""
        handle = ctx.resolve_device(device_id)
        data = get_wan_status(handle.read_only)
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_wan_status(data),
            }
        )

    @server.tool(name="peplink_supplemental_get_status_lan")
    def peplink_supplemental_get_status_lan(device_id: str | None = None) -> str:
        """Get LAN status (GET /api/status.lan — interface IPs)."""
        handle = ctx.resolve_device(device_id)
        data = get_lan_status(handle.read_only)
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_lan_status(data),
            }
        )

    @server.tool(name="peplink_supplemental_get_status_cpu")
    def peplink_supplemental_get_status_cpu(device_id: str | None = None) -> str:
        """Get CPU load (GET /api/status.cpu)."""
        handle = ctx.resolve_device(device_id)
        data = get_cpu_status(handle.read_only)
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_cpu_status(data),
            }
        )

    @server.tool(name="peplink_get_cmd_ap")
    def peplink_get_cmd_ap(device_id: str | None = None) -> str:
        """Check whether AP Controller commands are supported (GET /api/cmd.ap)."""
        handle = ctx.resolve_device(device_id)
        data = get_ap_cmd_support(handle.read_client_for_path("/api/cmd.ap"))
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_ap_cmd_support(data),
            }
        )

    @server.tool(name="peplink_get_cmd_ap_support")
    def peplink_get_cmd_ap_support(device_id: str | None = None) -> str:
        """Deprecated alias for peplink_get_cmd_ap."""
        return peplink_get_cmd_ap(device_id)

    @server.tool(name="peplink_get_status_extap_mesh")
    def peplink_get_status_extap_mesh(device_id: str | None = None) -> str:
        """Get external AP mesh status (read-only)."""
        handle = ctx.resolve_device(device_id)
        data = get_extap_mesh(handle.read_only)
        return _json({"device_id": handle.device_id, "host": handle.config.host, "mesh": data})

    @server.tool(name="peplink_get_status_extap_mesh_link")
    def peplink_get_status_extap_mesh_link(device_id: str | None = None) -> str:
        """Get external AP mesh link status (read-only)."""
        handle = ctx.resolve_device(device_id)
        data = get_extap_mesh_link(handle.read_only)
        return _json({"device_id": handle.device_id, "host": handle.config.host, "links": data})

    @server.tool(name="peplink_get_config_wan_connection")
    def peplink_get_config_wan_connection(device_id: str | None = None) -> str:
        """Get WAN connection configuration (read-only GET)."""
        handle = ctx.resolve_device(device_id)
        data = get_wan_connection_config(handle.read_client_for_path("/api/config.wan.connection"))
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_wan_connection_config(data),
            }
        )

    @server.tool(name="peplink_get_config_mesh")
    def peplink_get_config_mesh(device_id: str | None = None) -> str:
        """Get mesh configuration (read-only GET)."""
        handle = ctx.resolve_device(device_id)
        if handle.config.kind == "fusionhub":
            raise PeplinkConfigError(
                f"devices.{handle.device_id}: GET /api/config.mesh is unsupported on FusionHub"
            )
        data = get_mesh_config(handle.read_client_for_path("/api/config.mesh"))
        return _json({"device_id": handle.device_id, "host": handle.config.host, "mesh": data})

    @server.tool(name="peplink_get_config_ssid_profile")
    def peplink_get_config_ssid_profile(device_id: str | None = None) -> str:
        """Get SSID profile configuration (read-only GET)."""
        did, device = ctx.fleet.get_device(device_id)
        if device.kind == "ap":
            did, device = ctx.resolve_ap_snmp(device_id)
            assert device.snmp is not None and device.host
            data = fetch_ap_ssid_profile_config(device.host, device.snmp)
            return _json(
                {
                    "device_id": did,
                    "host": device.host,
                    "transport": "snmp",
                    **summarize_ssid_profiles(data),
                }
            )
        handle = ctx.resolve_device(device_id)
        data = get_ssid_profile_config(handle.read_client_for_path("/api/config.ssid.profile"))
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                "transport": "http",
                **summarize_ssid_profiles(data),
            }
        )

    @server.tool(name="peplink_get_config_port")
    def peplink_get_config_port(
        device_id: str | None = None,
        include_raw: bool = False,
    ) -> str:
        """Get port configuration (read-only GET /api/config.port).

        On gateway-managed switches (management=gateway), reads the switch directly
        when its IP is known. Switch Controller writes use the gateway with
        moduleType/moduleId/portId — see POST /api/config.port on the gateway.
        """
        handle, proxied_from = resolve_config_port_read_handle(ctx.registry, device_id)
        data = get_port_config(handle.read_client_for_path("/api/config.port"))
        payload: dict[str, Any] = {
            "device_id": handle.device_id,
            "host": handle.config.host,
            "management": handle.config.management,
            **summarize_port_config(data),
        }
        if proxied_from:
            payload["read_target"] = handle.device_id
            payload["requested_device_id"] = proxied_from
        if handle.config.management == "gateway" and handle.config.kind != "router":
            payload["write_gateway_id"] = management_gateway_id(handle.config, ctx.fleet)
        if include_raw:
            payload["raw"] = data
        return _json(payload)

    @server.tool(name="peplink_get_status_port")
    def peplink_get_status_port(device_id: str | None = None) -> str:
        """Get port link status (read-only GET /api/status.port on gateway/router)."""
        handle = ctx.resolve_device(device_id)
        if handle.config.kind in ("switch", "ap"):
            raise PeplinkConfigError(
                f"devices.{handle.device_id}: status.port is a gateway/router endpoint; "
                "use the gateway device_id (Switch Controller view)."
            )
        data = get_port_status(handle.read_only)
        return _json(
            {
                "device_id": handle.device_id,
                "host": handle.config.host,
                **summarize_port_status(data),
            }
        )

    @server.tool(name="peplink_get_status_device")
    def peplink_get_status_device(device_id: str | None = None) -> str:
        """Get device system status (AP: SNMP apSystem; not available on routers yet)."""
        did, device = ctx.resolve_ap_snmp(device_id)
        assert device.snmp is not None and device.host
        data = fetch_ap_device_status(device.host, device.snmp)
        return _json({"device_id": did, "host": device.host, "transport": "snmp", **data})

    @server.tool(name="peplink_get_status_wlan")
    def peplink_get_status_wlan(device_id: str | None = None) -> str:
        """Get WLAN radio/SSID status (AP: SNMP; routers use built-in AP endpoints separately)."""
        did, device = ctx.resolve_ap_snmp(device_id)
        assert device.snmp is not None and device.host
        data = fetch_ap_wlan_summary(device.host, device.snmp)
        return _json({"device_id": did, "host": device.host, "transport": "snmp", **data})

    @server.tool(name="peplink_snmp_get_ap_device_status")
    def peplink_snmp_get_ap_device_status(device_id: str | None = None) -> str:
        """Deprecated alias for peplink_get_status_device."""
        return peplink_get_status_device(device_id)

    @server.tool(name="peplink_snmp_get_ap_wlan_summary")
    def peplink_snmp_get_ap_wlan_summary(device_id: str | None = None) -> str:
        """Deprecated alias for peplink_get_status_wlan."""
        return peplink_get_status_wlan(device_id)

    @server.tool(name="peplink_snmp_get_ap_wlan_clients")
    def peplink_snmp_get_ap_wlan_clients(device_id: str | None = None) -> str:
        """Deprecated alias for peplink_get_status_client on kind=ap."""
        return peplink_get_status_client(device_id)

    @server.tool(name="peplink_doctor")
    def peplink_doctor(device_id: str | None = None) -> str:
        """Run connectivity/auth diagnostics for a device (read-only probe)."""
        did, _ = ctx.fleet.get_device(device_id)
        report = run_doctor(did, fleet=ctx.fleet)
        return _json(
            {
                "device_id": report.device_id,
                "host": report.host,
                "kind": report.kind,
                "transport": "snmp" if report.base_url.startswith("snmp://") else "http",
                "ok": report.ok,
                "tiers": [
                    {
                        "tier": t.tier,
                        "ok": t.ok,
                        "auth_type": t.auth_type,
                        "message": t.message,
                    }
                    for t in report.tiers
                ],
            }
        )

    register_manifest_tools(server, ctx)

    if ctx.fleet.ic2_enabled:
        register_ic2_tools(server, ctx)
        logger.info("InControl 2 cloud tools enabled (peplink_ic2_*)")

    return server, ctx


def _resolve_stdio_principal(ctx: AppContext) -> None:
    """Bind a principal for stdio mode from the environment.

    stdio has no per-request auth — the launching process is trusted — so the
    caller's tier is taken from PEPLINK_MCP_KEY (validated against configured
    keys) or PEPLINK_MCP_TIER (read_only|admin). Defaults to read_only.
    """
    import os

    from peplink_mcp_shared.mcp_keys import Principal, set_principal

    env_key = os.environ.get("PEPLINK_MCP_KEY")
    if env_key:
        principal = ctx.key_store.verify(env_key)
        if principal is None:
            raise PeplinkConfigError("PEPLINK_MCP_KEY does not match any configured mcp_keys")
        set_principal(Principal(principal.key_id, principal.tier, source="stdio-key"))
        logger.info("stdio principal: %s (tier=%s)", principal.key_id, principal.tier)
        return

    tier = os.environ.get("PEPLINK_MCP_TIER", "read_only").strip()
    if tier not in ("read_only", "admin"):
        raise PeplinkConfigError(f"PEPLINK_MCP_TIER must be read_only|admin, got: {tier}")
    set_principal(Principal("stdio-local", tier, source="stdio-env"))  # type: ignore[arg-type]
    logger.info("stdio principal: stdio-local (tier=%s)", tier)


def run_server(
    *,
    config_path: str | None = None,
    secrets_path: str | None = None,
    transport: str = "stdio",
    host: str | None = None,
    port: int | None = None,
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if transport == "stdio":
        server, ctx = create_server(config_path=config_path, secrets_path=secrets_path)
        _resolve_stdio_principal(ctx)
        logger.info("Starting peplink-device MCP (stdio)")
        server.run(transport="stdio")
        return

    if transport in ("http", "streamable-http"):
        _run_http(config_path=config_path, secrets_path=secrets_path, host=host, port=port)
        return

    raise PeplinkConfigError(f"unsupported transport: {transport} (use stdio|http)")


def _run_http(
    *,
    config_path: str | None,
    secrets_path: str | None,
    host: str | None,
    port: int | None,
) -> None:
    import uvicorn
    from peplink_mcp_shared.auth_middleware import BearerKeyMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    server, ctx = create_server(
        config_path=config_path, secrets_path=secrets_path, stateless_http=True
    )

    # Fail closed: HTTP exposes the server on the network, so refuse to serve
    # without at least one configured MCP key.
    if not ctx.key_store.configured:
        raise PeplinkConfigError(
            "HTTP transport requires at least one mcp_keys entry (with a secret in "
            "secrets.yaml). Add a key or use `keys generate`, or run with stdio."
        )

    bind_host = host or ctx.fleet.server.host
    bind_port = port or ctx.fleet.server.port

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "devices": len(ctx.fleet.devices),
                "mcp_keys": ctx.key_store.key_count,
                "access_mode": ctx.fleet.access_mode,
            }
        )

    app = server.streamable_http_app()
    app.router.routes.append(Route("/health", health, methods=["GET"]))
    app.add_middleware(BearerKeyMiddleware, store=ctx.key_store)

    logger.info(
        "Starting peplink-device MCP (http) on %s:%s — %d key(s), path=%s",
        bind_host,
        bind_port,
        ctx.key_store.key_count,
        server.settings.streamable_http_path,
    )
    uvicorn.run(app, host=bind_host, port=bind_port, log_level=ctx.fleet.logging.level.lower())
