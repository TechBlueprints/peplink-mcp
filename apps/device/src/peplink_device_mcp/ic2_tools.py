"""Register InControl 2 (cloud) MCP tools — namespace ``peplink_ic2_*``.

IC2 tools are co-located with the LAN device tools (same server) so one agent can
reason across both planes and route InControl-managed config changes to IC2. The
IC2 client and the device→IC2 identity cache live as closures here, keeping the
``peplink-ic2`` dependency out of ``peplink-mcp-shared``.

Read tools are open (like the device read tools). Config-write tools go through the
existing tier → policy → confirm gates (see ``_run_ic2_gates``).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from peplink_core.exceptions import PeplinkConfigError
from peplink_ic2 import IC2Client, resolve_ic2_target
from peplink_ic2.endpoints import config_device, config_group, inventory, reporting
from peplink_mcp_shared.audit import record_action
from peplink_mcp_shared.context import AppContext
from peplink_mcp_shared.policy import ConfirmationRequired

logger = logging.getLogger(__name__)

# Policy env flags (default-deny via PolicyGate) gating IC2 writes.
POLICY_CONFIG_WRITE = "PEPLINK_POLICY_ALLOW_IC2_CONFIG_WRITE"
POLICY_REBOOT = "PEPLINK_POLICY_ALLOW_IC2_REBOOT"
POLICY_FACTORY_RESET = "PEPLINK_POLICY_ALLOW_IC2_FACTORY_RESET"
POLICY_CONFIG_RESTORE = "PEPLINK_POLICY_ALLOW_IC2_CONFIG_RESTORE"

IC2_READ_TOOLS: frozenset[str] = frozenset(
    {
        "peplink_ic2_list_orgs",
        "peplink_ic2_list_groups",
        "peplink_ic2_list_devices",
        "peplink_ic2_get_device_status",
        "peplink_ic2_get_bandwidth_report",
        "peplink_ic2_list_config_backups",
    }
)

# Non-destructive InControl-managed config writes (Phase 4).
IC2_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "peplink_ic2_set_vlan_config",
        "peplink_ic2_delete_vlan_config",
        "peplink_ic2_put_ssid_settings",
        "peplink_ic2_put_ssid_profile",
        "peplink_ic2_put_radio_config",
        "peplink_ic2_put_firewall_rule_sets",
        "peplink_ic2_put_grouped_mac",
        "peplink_ic2_set_wan_priority",
    }
)

# Destructive ops (Phase 5) — double-gated (policy + confirm).
IC2_DESTRUCTIVE_TOOLS: frozenset[str] = frozenset(
    {
        "peplink_ic2_reboot_device",
        "peplink_ic2_factory_reset",
        "peplink_ic2_restore_config_backup",
    }
)

IC2_REGISTERED_TOOLS: frozenset[str] = (
    IC2_READ_TOOLS | IC2_WRITE_TOOLS | IC2_DESTRUCTIVE_TOOLS
)


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _parse_body(body: str | None) -> Any:
    if body in (None, "", "{}"):
        return {}
    try:
        return json.loads(body)
    except (TypeError, ValueError) as exc:
        raise PeplinkConfigError(f"body must be a JSON object/string: {exc}") from exc


def register_ic2_tools(server: FastMCP, ctx: AppContext) -> list[str]:
    """Register IC2 MCP tools. Requires ``ctx.fleet.ic2_enabled``."""
    ic2 = ctx.fleet.incontrol2
    read_creds = ic2.read_credentials()
    if read_creds is None:  # pragma: no cover - guarded by ic2_enabled at call site
        raise PeplinkConfigError("incontrol2 has no credentials configured")

    # Read calls (and target resolution) use the read credential; writes use the
    # admin/RW credential. A single incontrol2.auth serves as both.
    client = IC2Client(read_creds, base_url=ic2.base_url, verify_tls=ic2.verify_tls)
    write_creds = ic2.write_credentials()
    write_client = (
        IC2Client(write_creds, base_url=ic2.base_url, verify_tls=ic2.verify_tls)
        if write_creds is not None
        else None
    )

    def _require_write_client() -> IC2Client:
        if write_client is None:
            raise PeplinkConfigError(
                "InControl 2 write requires a write-capable credential "
                "(incontrol2.admin or incontrol2.auth); only incontrol2.read_only is set"
            )
        return write_client

    target_cache: dict = {}
    registered: list[str] = []

    def _resolve_target(device_id: str | None):
        did, device = ctx.fleet.get_device(device_id)
        if device.ic2 is None:
            raise PeplinkConfigError(
                f"devices.{did}.ic2 mapping not configured (need serial or org/group/device ids)"
            )
        target = resolve_ic2_target(
            client,
            device.ic2,
            default_org_id=ic2.default_org_id,
            cache=target_cache,
            cache_key=did,
        )
        return did, target

    def _group_scope(
        device_id: str | None, org_id: str | None, group_id: str | None
    ) -> tuple[str, str, str | None]:
        """Resolve (org, group, audit_label) for a group-scoped write.

        Either pass ``device_id`` (resolves to its IC2 org+group) or explicit
        ``org_id``+``group_id`` (org defaults to incontrol2.default_org_id).
        """
        if device_id is not None:
            did, target = _resolve_target(device_id)
            return target.org_id, target.group_id, did
        org = org_id or ic2.default_org_id
        if not org or not group_id:
            raise PeplinkConfigError(
                "provide device_id, or both org_id (or default_org_id) and group_id"
            )
        return org, group_id, None

    def _write_gates(
        *, tool: str, method: str, path: str, audit_device: str, policy_key: str, confirm: bool
    ) -> None:
        """admin tier -> policy flag -> confirm. Audits denials and the allow."""
        principal = ctx.current_principal()
        try:
            ctx.require_tier("admin")
            ctx.require_policy(policy_key, tool=tool)
            if not confirm:
                raise ConfirmationRequired(tool, f"{method} {path}")
        except Exception as exc:
            record_action(
                principal,
                tool=tool,
                method=method,
                path=path,
                device_id=audit_device,
                decision=f"deny:{type(exc).__name__}",
                detail=str(exc),
            )
            raise
        record_action(
            principal,
            tool=tool,
            method=method,
            path=path,
            device_id=audit_device,
            decision="allow",
        )

    # -- Phase A: reads ---------------------------------------------------

    @server.tool(name="peplink_ic2_list_orgs")
    def peplink_ic2_list_orgs() -> str:
        """List InControl 2 organizations accessible to the configured credentials."""
        return _json(inventory.summarize_orgs(inventory.list_orgs(client)))

    @server.tool(name="peplink_ic2_list_groups")
    def peplink_ic2_list_groups(org_id: str | None = None) -> str:
        """List groups in an IC2 organization (defaults to incontrol2.default_org_id)."""
        org = org_id or ic2.default_org_id
        if not org:
            raise PeplinkConfigError("org_id required (no incontrol2.default_org_id configured)")
        return _json(
            {"org_id": org, **inventory.summarize_groups(inventory.list_groups(client, org))}
        )

    @server.tool(name="peplink_ic2_list_devices")
    def peplink_ic2_list_devices(org_id: str | None = None, group_id: str | None = None) -> str:
        """List devices in an IC2 org (optionally scoped to a group)."""
        org = org_id or ic2.default_org_id
        if not org:
            raise PeplinkConfigError("org_id required (no incontrol2.default_org_id configured)")
        data = inventory.list_devices(client, org, group_id)
        return _json(
            {"org_id": org, "group_id": group_id, **inventory.summarize_devices(data)}
        )

    @server.tool(name="peplink_ic2_get_device_status")
    def peplink_ic2_get_device_status(device_id: str | None = None) -> str:
        """Get a device's IC2 status/detail. Resolves a fleet device_id to its IC2 identity."""
        did, target = _resolve_target(device_id)
        data = inventory.get_device_detail(
            client, target.org_id, target.group_id, target.device_id
        )
        return _json(
            {
                "device_id": did,
                "ic2": {
                    "org_id": target.org_id,
                    "group_id": target.group_id,
                    "device_id": target.device_id,
                },
                **inventory.summarize_device_detail(data),
            }
        )

    @server.tool(name="peplink_ic2_get_bandwidth_report")
    def peplink_ic2_get_bandwidth_report(device_id: str | None = None) -> str:
        """Get a device's bandwidth usage report from InControl 2."""
        did, target = _resolve_target(device_id)
        data = reporting.get_device_bandwidth(
            client, target.org_id, target.group_id, target.device_id
        )
        return _json(
            {
                "device_id": did,
                "ic2": {
                    "org_id": target.org_id,
                    "group_id": target.group_id,
                    "device_id": target.device_id,
                },
                "bandwidth": data,
            }
        )

    @server.tool(name="peplink_ic2_list_config_backups")
    def peplink_ic2_list_config_backups(device_id: str | None = None) -> str:
        """List a device's InControl 2 config backups (id + metadata)."""
        did, target = _resolve_target(device_id)
        data = config_device.list_config_backups(
            client, target.org_id, target.group_id, target.device_id
        )
        return _json({"device_id": did, "backups": data})

    # -- Phase B: InControl-managed config writes (admin + policy + confirm)

    def _group_write(tool, method, path_tail, fn, body_hint="", policy_key=POLICY_CONFIG_WRITE):
        def handler(
            body: str = "{}",
            device_id: str | None = None,
            org_id: str | None = None,
            group_id: str | None = None,
            confirm: bool = False,
        ) -> str:
            org, grp, label = _group_scope(device_id, org_id, group_id)
            path = f"/rest/o/{org}/g/{grp}/{path_tail}"
            _write_gates(
                tool=tool,
                method=method,
                path=path,
                audit_device=label or grp,
                policy_key=policy_key,
                confirm=confirm,
            )
            data = fn(_require_write_client(), org, grp, _parse_body(body))
            return _json({"org_id": org, "group_id": grp, "path": path, "result": data})

        handler.__name__ = tool
        handler.__doc__ = (
            f"{method} {path_tail} for an InControl 2 group (InControl-managed config "
            "write). Target the group via device_id (resolves its group) or org_id+group_id. "
            "`body` is the config JSON object. Admin tier; requires "
            f"{POLICY_CONFIG_WRITE}=1 and confirm=true."
            + (f"\n\n{body_hint}" if body_hint else "")
        )
        return handler

    server.tool(name="peplink_ic2_set_vlan_config")(
        _group_write(
            "peplink_ic2_set_vlan_config",
            "POST",
            "vlan_config",
            config_group.update_vlan_config,
            body_hint=(
                "body = {\"data\": vlan_config_obj}. vlan_config_obj fields: id (int, omit "
                "to create), name, vlan_id (int), tags ('none'|'include'|'exclude'), "
                "device_tag_ids (int[]), balancemax_enabled, switch_enabled, ip_address, "
                "netmask, l2_isolation (false=inter-VLAN routing on), portal_enabled, "
                "portal_id, dhcp_server_enabled, dhcp_server_settings, dns_server_1/2, "
                "default_vlan. See raw-sources/docs/peplink/incontrol2/write-schemas.md."
            ),
        )
    )
    server.tool(name="peplink_ic2_put_ssid_settings")(
        _group_write(
            "peplink_ic2_put_ssid_settings",
            "PUT",
            "ssid_settings",
            config_group.put_ssid_settings,
            body_hint=(
                "body = ssid_detail {id, country, default_band, wifi_mgm_enabled, "
                "modules[device_radio_module], ssid_profiles[ssid_profile]}. ssid_profile "
                "fields: vlan_id, broadcast (false=hidden), radio_select ('1'=2.4G/'2'=5G/"
                "'3'=both), band_steering, acl_id (MAC ACL), mac_filter, mac_list[], "
                "fast_transition, igmp_snooping, portal_enabled, portal_url. Schema: "
                "write-schemas.md (request mirrors GET ssid_profiles)."
            ),
        )
    )
    server.tool(name="peplink_ic2_put_radio_config")(
        _group_write(
            "peplink_ic2_put_radio_config",
            "PUT",
            "put_radio_config",
            config_group.put_radio_config,
            body_hint=(
                "body = device_radio_module {id, device_id, boost, channel, frequency_band, "
                "power, product_id, wifi_cfg} (or a list under 'data'). See write-schemas.md."
            ),
        )
    )
    server.tool(name="peplink_ic2_put_firewall_rule_sets")(
        _group_write(
            "peplink_ic2_put_firewall_rule_sets",
            "PUT",
            "firewall_rule_sets",
            config_group.put_firewall_rule_sets,
            body_hint=(
                "body = the firewall rule-set object (not modeled in the IC2 reference; "
                "mirrors the device firewall rule-set structure). Forwarded verbatim."
            ),
        )
    )
    server.tool(name="peplink_ic2_put_grouped_mac")(
        _group_write(
            "peplink_ic2_put_grouped_mac",
            "PUT",
            "grouped_mac",
            config_group.put_grouped_mac,
            body_hint=(
                "body = access_control_list {id (omit to create), name, address (string[] of "
                "MAC addresses)}. Companion: POST/DELETE .../grouped_mac/{acl_id}."
            ),
        )
    )

    # SSID profile and VLAN-delete need an id path segment — handled explicitly.
    @server.tool(name="peplink_ic2_put_ssid_profile")
    def peplink_ic2_put_ssid_profile(
        ssid_id: str,
        body: str = "{}",
        device_id: str | None = None,
        org_id: str | None = None,
        group_id: str | None = None,
        confirm: bool = False,
    ) -> str:
        """Update one SSID profile in an InControl 2 group (admin; needs confirm + policy).

        body = ssid_profile {vlan_id, broadcast (false=hidden), radio_select
        ('1'=2.4G/'2'=5G/'3'=both), band_steering, acl_id, mac_filter, mac_list[],
        fast_transition, igmp_snooping, portal_*}. See write-schemas.md.
        """
        org, grp, label = _group_scope(device_id, org_id, group_id)
        path = f"/rest/o/{org}/g/{grp}/ssid_profiles/{ssid_id}"
        _write_gates(
            tool="peplink_ic2_put_ssid_profile",
            method="PUT",
            path=path,
            audit_device=label or grp,
            policy_key=POLICY_CONFIG_WRITE,
            confirm=confirm,
        )
        data = config_group.put_ssid_profile(
            _require_write_client(), org, grp, ssid_id, _parse_body(body)
        )
        return _json({"org_id": org, "group_id": grp, "path": path, "result": data})

    @server.tool(name="peplink_ic2_delete_vlan_config")
    def peplink_ic2_delete_vlan_config(
        vlan_id: str,
        device_id: str | None = None,
        org_id: str | None = None,
        group_id: str | None = None,
        confirm: bool = False,
    ) -> str:
        """Delete a VLAN profile from an InControl 2 group (admin; needs confirm + policy)."""
        org, grp, label = _group_scope(device_id, org_id, group_id)
        path = f"/rest/o/{org}/g/{grp}/vlan_config/{vlan_id}"
        _write_gates(
            tool="peplink_ic2_delete_vlan_config",
            method="DELETE",
            path=path,
            audit_device=label or grp,
            policy_key=POLICY_CONFIG_WRITE,
            confirm=confirm,
        )
        data = config_group.delete_vlan_config(_require_write_client(), org, grp, vlan_id)
        return _json({"org_id": org, "group_id": grp, "path": path, "result": data})

    @server.tool(name="peplink_ic2_set_wan_priority")
    def peplink_ic2_set_wan_priority(
        body: str,
        device_id: str | None = None,
        confirm: bool = False,
    ) -> str:
        """Set a device's WAN failover priority via InControl 2 (admin; needs confirm + policy).

        body = the WAN priority assignment (not modeled in the IC2 reference; returns a
        ws_command {json, success, command_id} dispatched to the device). Forwarded verbatim.
        """
        did, target = _resolve_target(device_id)
        path = f"/rest/o/{target.org_id}/g/{target.group_id}/d/{target.device_id}/wan/priority"
        _write_gates(
            tool="peplink_ic2_set_wan_priority",
            method="POST",
            path=path,
            audit_device=did,
            policy_key=POLICY_CONFIG_WRITE,
            confirm=confirm,
        )
        data = config_device.set_wan_priority(
            _require_write_client(), target.org_id, target.group_id, target.device_id,
            _parse_body(body),
        )
        return _json({"device_id": did, "path": path, "result": data})

    # -- Phase B: destructive (admin + dedicated policy + confirm) --------

    def _device_destructive(tool, policy_key, fn, method="POST", suffix=""):
        def handler(device_id: str | None = None, confirm: bool = False) -> str:
            did, target = _resolve_target(device_id)
            path = f"/rest/o/{target.org_id}/g/{target.group_id}/d/{target.device_id}{suffix}"
            _write_gates(
                tool=tool,
                method=method,
                path=path,
                audit_device=did,
                policy_key=policy_key,
                confirm=confirm,
            )
            data = fn(_require_write_client(), target.org_id, target.group_id, target.device_id)
            return _json({"device_id": did, "path": path, "result": data})

        handler.__name__ = tool
        handler.__doc__ = (
            f"DESTRUCTIVE InControl 2 device op ({suffix.lstrip('/')}). Admin tier; "
            f"requires {policy_key}=1 in the server env and confirm=true."
        )
        return handler

    server.tool(name="peplink_ic2_reboot_device")(
        _device_destructive(
            "peplink_ic2_reboot_device", POLICY_REBOOT, config_device.reboot_device,
            suffix="/tools/reboot",
        )
    )
    server.tool(name="peplink_ic2_factory_reset")(
        _device_destructive(
            "peplink_ic2_factory_reset", POLICY_FACTORY_RESET, config_device.reset_to_default,
            suffix="/tools/reset_default",
        )
    )

    @server.tool(name="peplink_ic2_restore_config_backup")
    def peplink_ic2_restore_config_backup(
        backup_id: str,
        device_id: str | None = None,
        confirm: bool = False,
    ) -> str:
        """Restore an InControl 2 config backup to a device (admin; needs confirm + policy).

        DESTRUCTIVE — overwrites the device configuration. List backup ids first with
        peplink_ic2_list_config_backups.
        """
        did, target = _resolve_target(device_id)
        path = (
            f"/rest/o/{target.org_id}/g/{target.group_id}/d/{target.device_id}"
            f"/config_backup/{backup_id}/restore"
        )
        _write_gates(
            tool="peplink_ic2_restore_config_backup",
            method="POST",
            path=path,
            audit_device=did,
            policy_key=POLICY_CONFIG_RESTORE,
            confirm=confirm,
        )
        data = config_device.restore_config_backup(
            _require_write_client(), target.org_id, target.group_id, target.device_id, backup_id
        )
        return _json({"device_id": did, "path": path, "result": data})

    registered.extend(sorted(IC2_REGISTERED_TOOLS))
    logger.info("Registered %d InControl 2 MCP tools", len(registered))
    return registered
