"""Config endpoint helpers (read-only GETs)."""

from __future__ import annotations

from typing import Any

from peplink_core.client import PeplinkDeviceClient


def get_wan_connection_config(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/config.wan.connection")


def summarize_wan_connection_config(data: dict[str, Any]) -> dict[str, Any]:
    order = data.get("order", [])
    profiles = []
    for wid in order:
        entry = data.get(str(wid), {})
        if not isinstance(entry, dict):
            continue
        profiles.append(
            {
                "id": wid,
                "name": entry.get("name"),
                "enable": entry.get("enable"),
                "type": entry.get("type"),
                "priority": entry.get("priority"),
            }
        )
    return {"profile_count": len(order), "profiles": profiles}


def get_mesh_config(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/config.mesh")


def get_ssid_profile_config(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/config.ssid.profile")


def get_port_config(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/config.port")


def summarize_port_config(data: dict[str, Any]) -> dict[str, Any]:
    modules: list[dict[str, Any]] = []
    for mod_type in data.get("order", []):
        mod = data.get(mod_type, {})
        if not isinstance(mod, dict):
            continue
        mod_ids = mod.get("order", [])
        port_count = 0
        for mid in mod_ids:
            item = mod.get(str(mid), mod.get(mid, {}))
            if not isinstance(item, dict):
                continue
            ports = item.get("port", {})
            if isinstance(ports, dict):
                port_count += len(ports.get("order", []))
        modules.append(
            {
                "module_type": mod_type,
                "slot_count": len(mod_ids),
                "port_count": port_count,
            }
        )
    link_agg = data.get("linkAggregation", {})
    link_order = link_agg.get("order", []) if isinstance(link_agg, dict) else []
    return {
        "module_count": len(modules),
        "modules": modules,
        "link_aggregation_count": len(link_order),
    }


def summarize_ssid_profiles(data: dict[str, Any]) -> dict[str, Any]:
    order = data.get("order", [])
    profiles = []
    for sid in order:
        entry = data.get(str(sid), {})
        if not isinstance(entry, dict):
            continue
        profiles.append(
            {
                "id": sid,
                "name": entry.get("name"),
                "enable": entry.get("enable"),
                "ssid": entry.get("ssid"),
            }
        )
    return {"profile_count": len(order), "profiles": profiles}


def get_admin_config(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/config.admin")


def summarize_admin_config(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "device_name": data.get("name"),
        "user_login": data.get("userLogin"),
        "cli_enabled": data.get("cli", {}).get("enable") if isinstance(data.get("cli"), dict) else None,
        "management_external_access": data.get("managementExternalAccess")
        or data.get("wanAccess"),
    }


def get_incontrol_config(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/config.incontrol")


def summarize_incontrol_config(data: dict[str, Any]) -> dict[str, Any]:
    enabled = data.get("enable")
    readonly = data.get("readonlyMode")
    # Routing hint: when the device is InControl-managed (enabled) and especially in
    # readonly_mode, config changes should be made through InControl 2 (peplink_ic2_*
    # tools), not the device's local API — the local API may be locked or overwritten.
    if enabled and readonly:
        authority = "ic2"
    elif enabled:
        authority = "ic2_managed"
    else:
        authority = "device"
    return {
        "enable": enabled,
        "readonly_mode": readonly,
        "configured": bool(data),
        "config_authority_hint": authority,
    }


def get_lan_config(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/config.lan")


def summarize_lan_config(data: dict[str, Any]) -> dict[str, Any]:
    order = data.get("order", [])
    if isinstance(order, list) and order:
        return {"profile_count": len(order), "profile_ids": order[:20]}
    keys = [k for k in data if k not in ("order", "reference")]
    return {"section_keys": keys[:20], "section_count": len(keys)}


def get_snmp_info_config(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/config.snmp.info")


def summarize_snmp_info_config(data: dict[str, Any]) -> dict[str, Any]:
    v1 = data.get("v1") if isinstance(data.get("v1"), dict) else {}
    v2 = data.get("v2") if isinstance(data.get("v2"), dict) else {}
    v3 = data.get("v3") if isinstance(data.get("v3"), dict) else {}
    return {
        "name": data.get("name"),
        "port": data.get("port"),
        "v1_enable": v1.get("enable"),
        "v2_enable": v2.get("enable"),
        "v3_enable": v3.get("enable"),
        "snmp_trap_enable": data.get("snmpTrap", {}).get("enable")
        if isinstance(data.get("snmpTrap"), dict)
        else None,
    }


def get_pepvpn_config(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/config.pepvpn")


def summarize_pepvpn_config(data: dict[str, Any]) -> dict[str, Any]:
    healthcheck = data.get("healthcheck") if isinstance(data.get("healthcheck"), dict) else {}
    reference = data.get("reference") if isinstance(data.get("reference"), dict) else {}
    reserved = reference.get("reservedPort") if isinstance(reference.get("reservedPort"), dict) else {}
    return {
        "site_id": data.get("siteId"),
        "healthcheck_mode": healthcheck.get("mode"),
        "default_site_id": reference.get("defaultSiteId"),
        "reserved_ports": reserved.get("order", [])[:10],
    }


def get_pepvpn_profile_config(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/config.pepvpn.profile")


def summarize_pepvpn_profile_config(data: dict[str, Any]) -> dict[str, Any]:
    order = data.get("order", [])
    profiles = []
    for pid in order:
        entry = data.get(str(pid), {})
        if not isinstance(entry, dict):
            continue
        auth = entry.get("authentication") if isinstance(entry.get("authentication"), dict) else {}
        peers = []
        for detail in auth.get("detail") or []:
            if not isinstance(detail, dict):
                continue
            peers.append(
                {
                    "remote_id": detail.get("remoteId"),
                    "psk": "[redacted]" if detail.get("psk") else None,
                }
            )
        data_port = entry.get("dataPort") if isinstance(entry.get("dataPort"), dict) else {}
        protocol = data_port.get("protocol") if isinstance(data_port.get("protocol"), dict) else {}
        wan = entry.get("wan") if isinstance(entry.get("wan"), dict) else {}
        profiles.append(
            {
                "id": pid,
                "name": entry.get("name"),
                "enable": entry.get("enable"),
                "encryption": entry.get("encryption"),
                "auth_type": auth.get("type"),
                "remote_peers": peers,
                "data_port": protocol.get("port"),
                "wan_ids": wan.get("order", []) if isinstance(wan.get("order"), list) else [],
                "incontrol_managed": entry.get("incontrolManaged"),
            }
        )
    return {"profile_count": len(profiles), "profiles": profiles}


def get_firewall_config(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/config.firewall")


def _firewall_rule_count(section: Any) -> int:
    if not isinstance(section, dict):
        return 0
    rule = section.get("rule")
    if not isinstance(rule, dict):
        return 0
    order = rule.get("order", [])
    return len(order) if isinstance(order, list) else 0


def summarize_firewall_config(data: dict[str, Any]) -> dict[str, Any]:
    outbound = data.get("outbound") if isinstance(data.get("outbound"), dict) else {}
    inbound = data.get("inbound") if isinstance(data.get("inbound"), dict) else {}
    private = data.get("private") if isinstance(data.get("private"), dict) else {}
    return {
        "outbound_policy": outbound.get("policy"),
        "outbound_rule_count": _firewall_rule_count(outbound),
        "inbound_policy": inbound.get("policy"),
        "inbound_rule_count": _firewall_rule_count(inbound),
        "private_policy": private.get("policy"),
        "private_rule_count": _firewall_rule_count(private),
        "local_traffic": data.get("localTraffic"),
        "ids_enabled": data.get("ids"),
    }


def get_nat_mapping_config(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/config.natMapping")


def summarize_nat_mapping_config(data: dict[str, Any]) -> dict[str, Any]:
    single = data.get("single") if isinstance(data.get("single"), dict) else {}
    pool = data.get("pool") if isinstance(data.get("pool"), dict) else {}
    return {
        "single_mapping_count": len(single),
        "pool_mapping_count": len(pool),
    }


def get_dhcp_config(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/config.dhcp")


def summarize_dhcp_config(data: dict[str, Any]) -> dict[str, Any]:
    reference = data.get("reference") if isinstance(data.get("reference"), dict) else {}
    return {
        "enable": data.get("enable"),
        "has_speedfusion_nat": reference.get("hasSpeedfusionNat"),
    }


def get_dns_config(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/config.dns")


def summarize_dns_config(data: dict[str, Any]) -> dict[str, Any]:
    zone = data.get("zoneTransfer") if isinstance(data.get("zoneTransfer"), dict) else {}
    subnet_db = data.get("subnetDatabase") if isinstance(data.get("subnetDatabase"), dict) else {}
    return {
        "zone_transfer_enable": zone.get("enable"),
        "subnet_database_enable": subnet_db.get("enable"),
    }


def get_schedule_config(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/config.schedule")


def summarize_schedule_config(data: dict[str, Any]) -> dict[str, Any]:
    rule = data.get("rule") if isinstance(data.get("rule"), dict) else {}
    order = rule.get("order", [])
    return {
        "enable": data.get("enable"),
        "rule_count": len(order) if isinstance(order, list) else 0,
    }


def get_wan_config(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/config.wan")


def summarize_wan_config(data: dict[str, Any]) -> dict[str, Any]:
    order = data.get("order", [])
    profiles = []
    for wid in order:
        entry = data.get(str(wid), {})
        if not isinstance(entry, dict):
            continue
        conn = entry.get("connection") if isinstance(entry.get("connection"), dict) else {}
        method = conn.get("method") if isinstance(conn.get("method"), dict) else {}
        profiles.append(
            {
                "id": wid,
                "name": entry.get("name"),
                "enable": entry.get("enable"),
                "active": entry.get("active"),
                "routing_mode": conn.get("routingMode"),
                "method_type": method.get("type"),
            }
        )
    return {"profile_count": len(profiles), "profiles": profiles}


def get_gpio_config(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/config.gpio")


def summarize_gpio_config(data: dict[str, Any]) -> dict[str, Any]:
    order = data.get("order", [])
    return {"gpio_count": len(order) if isinstance(order, list) else 0}


def get_wan_connection_priority_config(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/config.wan.connection.priority")


def summarize_wan_connection_priority_config(data: dict[str, Any]) -> dict[str, Any]:
    order = data.get("order", [])
    entries = []
    for wid in order:
        entry = data.get(str(wid), {})
        if not isinstance(entry, dict):
            continue
        entries.append(
            {
                "id": wid,
                "name": entry.get("name"),
                "group": entry.get("group"),
                "priority": entry.get("priority"),
                "enable": entry.get("enable"),
            }
        )
    return {"entry_count": len(entries), "entries": entries}
