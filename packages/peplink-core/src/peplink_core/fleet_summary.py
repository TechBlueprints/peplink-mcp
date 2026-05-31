"""Human-readable fleet summaries for CLI and MCP list tools."""

from __future__ import annotations

from peplink_core.config import DeviceAuth, FleetConfig


def auth_type_label(auth: DeviceAuth) -> str:
    return auth.type


def device_auth_summary(device_id: str, fleet: FleetConfig) -> dict:
    device = fleet.devices[device_id]
    auth = device.auth
    host_source = "discovered" if device.discover and device.host else "static"
    if device.discover and not device.host:
        host_source = "pending_discovery"
    row = {
        "device_id": device_id,
        "host": device.host,
        "host_source": host_source,
        "kind": device.kind,
        "management": device.management,
        "transport": "snmp" if device.kind == "ap" else "http",
        "firmware_hint": device.firmware_hint,
        "default": fleet.defaults.device_id == device_id,
        "auth_configured": (
            (auth is not None and auth.read_only is not None)
            or (device.kind == "ap" and device.snmp is not None)
        ),
        "config_read_configured": bool(auth and auth.config_read),
        "admin_configured": bool(auth and auth.admin),
        "snmp_configured": device.snmp is not None,
        "site": fleet.effective_site(device_id),
        "ic2_serial": device.ic2.serial if device.ic2 else None,
    }
    if device.kind == "ap" and device.snmp is not None:
        row["read_only_auth"] = "snmp"
    elif auth and auth.read_only:
        row["read_only_auth"] = auth_type_label(auth.read_only)
    if auth and auth.config_read:
        row["config_read_auth"] = auth_type_label(auth.config_read)
    if auth and auth.admin:
        row["admin_auth"] = auth_type_label(auth.admin)
    if device.discover:
        row["discover_via"] = device.discover.via or fleet.defaults.gateway_id
        row["discover_match"] = device.discover.match
    if device.management == "gateway":
        row["management_gateway_id"] = (
            device.discover.via if device.discover and device.discover.via else fleet.defaults.gateway_id
        )
    return row


def fleet_device_summaries(fleet: FleetConfig) -> list[dict]:
    return [device_auth_summary(did, fleet) for did in sorted(fleet.devices)]


def fleet_capabilities(fleet: FleetConfig) -> dict:
    return {
        "access_mode": fleet.access_mode,
        "admin_tools_enabled": fleet.admin_tools_enabled,
        "ic2_enabled": fleet.ic2_enabled,
        "default_device_id": fleet.defaults.device_id,
        "gateway_id": fleet.defaults.gateway_id,
        "sites": fleet.sites(),
    }
