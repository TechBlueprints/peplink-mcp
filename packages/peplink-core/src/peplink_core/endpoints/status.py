"""Status endpoint helpers."""

from __future__ import annotations

from typing import Any

from peplink_core.client import PeplinkDeviceClient


def get_wan_connection(
    client: PeplinkDeviceClient,
    *,
    lite: bool = True,
    conn_ids: list[int] | None = None,
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if lite:
        query["lite"] = "yes"
    if conn_ids:
        query["id"] = ",".join(str(i) for i in conn_ids)
    return client.request("GET", "/api/status.wan.connection", query=query or None)


def summarize_wan_connection(data: dict[str, Any]) -> dict[str, Any]:
    order = data.get("order", [])
    connections = []
    for wid in order:
        entry = data.get(str(wid), {})
        if not isinstance(entry, dict):
            continue
        connections.append(
            {
                "id": wid,
                "name": entry.get("name"),
                "enable": entry.get("enable"),
                "statusLed": entry.get("statusLed"),
                "message": entry.get("message"),
                "ip": entry.get("ip"),
                "type": entry.get("type"),
                "uptime": entry.get("uptime"),
                "priority": entry.get("priority"),
            }
        )
    enabled = sum(1 for c in connections if c.get("enable"))
    return {
        "wan_count": len(order),
        "enabled_count": enabled,
        "connections": connections,
    }


def get_pepvpn(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/status.pepvpn")


def summarize_pepvpn(data: dict[str, Any]) -> dict[str, Any]:
    profiles_obj = data.get("profile") or {}
    profiles = []
    if isinstance(profiles_obj, dict):
        for pid, profile in profiles_obj.items():
            if pid in ("order", "siteId") or not isinstance(profile, dict):
                continue
            profiles.append(
                {
                    "id": pid,
                    "name": profile.get("name"),
                    "type": profile.get("type"),
                    "status": profile.get("status"),
                    "peer_count": profile.get("peerCount"),
                }
            )

    peers_obj = data.get("peer") or []
    peers = []
    if isinstance(peers_obj, list):
        for peer in peers_obj:
            if not isinstance(peer, dict):
                continue
            peers.append(
                {
                    "peer_id": peer.get("peerId"),
                    "profile_id": peer.get("profileId"),
                    "name": peer.get("name") or peer.get("username"),
                    "status": peer.get("status"),
                    "serial_number": peer.get("serialNumber"),
                    "routes": peer.get("route") or [],
                }
            )
    elif isinstance(peers_obj, dict):
        for pid, peer in peers_obj.items():
            if not isinstance(peer, dict):
                continue
            peers.append(
                {
                    "peer_id": pid,
                    "name": peer.get("name") or peer.get("username"),
                    "status": peer.get("status"),
                    "serial_number": peer.get("serialNumber"),
                    "routes": peer.get("route") or [],
                }
            )

    site_id = profiles_obj.get("siteId") if isinstance(profiles_obj, dict) else None
    return {
        "site_id": site_id,
        "profile_count": len(profiles),
        "profiles": profiles,
        "peer_count": len(peers),
        "peers": peers,
    }


def get_clients(
    client: PeplinkDeviceClient,
    *,
    active_only: bool = True,
) -> dict[str, Any]:
    return client.request(
        "GET",
        "/api/status.client",
        query={"activeOnly": "yes" if active_only else "no"},
    )


def summarize_clients(data: dict[str, Any], *, limit: int = 50) -> dict[str, Any]:
    items = data.get("list") or data.get("client") or []
    if not isinstance(items, list):
        items = []
    summarized = []
    for entry in items[:limit]:
        if not isinstance(entry, dict):
            continue
        summarized.append(
            {
                "name": entry.get("name"),
                "ip": entry.get("ip"),
                "mac": entry.get("mac"),
                "active": entry.get("active"),
                "connectionType": entry.get("connectionType"),
            }
        )
    return {
        "total_reported": len(items),
        "returned": len(summarized),
        "truncated": len(items) > limit,
        "clients": summarized,
    }


def get_lan_profile(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/status.lan.profile")


def summarize_lan_profile(data: dict[str, Any]) -> dict[str, Any]:
    order = data.get("order", [])
    profiles = []
    for pid in order:
        entry = data.get(str(pid), {})
        if not isinstance(entry, dict):
            continue
        profiles.append(
            {
                "id": pid,
                "name": entry.get("name"),
                "vlanId": entry.get("vlanId"),
                "ip": entry.get("ip"),
            }
        )
    return {"profile_count": len(order), "profiles": profiles}


def get_wan_connection_allowance(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/status.wan.connection.allowance")


def get_extap_mesh(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/status.extap.mesh")


def get_extap_mesh_link(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/status.extap.mesh.link")


def get_port_status(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/status.port")


def summarize_port_status(data: dict[str, Any]) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    for section in ("lan", "wan"):
        block = data.get(section, {})
        if not isinstance(block, dict):
            continue
        order = block.get("order", [])
        ports = []
        for pid in order:
            entry = block.get(str(pid), block.get(pid, {}))
            if not isinstance(entry, dict):
                continue
            ports.append(
                {
                    "id": pid,
                    "name": entry.get("name"),
                    "enable": entry.get("enable"),
                    "linkUp": entry.get("linkUp"),
                }
            )
        sections.append({"section": section, "port_count": len(order), "ports": ports})
    return {"sections": sections}


def get_traffic(client: PeplinkDeviceClient, *, fetch_delay: int = 1) -> dict[str, Any]:
    return client.request("GET", "/api/status.traffic", query={"fetchDelay": fetch_delay})


def summarize_traffic(data: dict[str, Any]) -> dict[str, Any]:
    bandwidth = data.get("bandwidth", {}) if isinstance(data.get("bandwidth"), dict) else {}
    traffic = data.get("traffic", {}) if isinstance(data.get("traffic"), dict) else {}
    bw_order = bandwidth.get("order", []) if isinstance(bandwidth, dict) else []
    streams = []
    for wid in bw_order[:10]:
        entry = bandwidth.get(str(wid), bandwidth.get(wid, {}))
        if not isinstance(entry, dict):
            continue
        overall = entry.get("overall", {}) if isinstance(entry.get("overall"), dict) else {}
        streams.append(
            {
                "id": wid,
                "name": entry.get("name"),
                "download_kbps": overall.get("download"),
                "upload_kbps": overall.get("upload"),
            }
        )
    lifetime = data.get("lifetime", {}) if isinstance(data.get("lifetime"), dict) else {}
    return {
        "bandwidth_unit": bandwidth.get("unit"),
        "traffic_unit": traffic.get("unit"),
        "lifetime_unit": lifetime.get("unit"),
        "stream_count": len(bw_order),
        "streams": streams,
    }


def get_status_log(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/status.log")


def summarize_status_log(data: dict[str, Any], *, limit: int = 20) -> dict[str, Any]:
    lines = data.get("log", [])
    if not isinstance(lines, list):
        lines = []
    return {
        "line_count": len(lines),
        "is_end_of_log": data.get("is_end_of_log"),
        "returned": min(len(lines), limit),
        "truncated": len(lines) > limit,
        "log": lines[:limit],
    }


def get_wan_latency(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/status.wan.latency")


def summarize_wan_latency(data: dict[str, Any]) -> dict[str, Any]:
    order = data.get("order", [])
    wans = []
    for wid in order:
        entry = data.get(str(wid), {})
        if not isinstance(entry, dict):
            continue
        latency = entry.get("latency", {}) if isinstance(entry.get("latency"), dict) else {}
        data_points = latency.get("data", []) if isinstance(latency.get("data"), list) else []
        recent = [v for v in data_points[-30:] if isinstance(v, (int, float)) and v > 0]
        wans.append(
            {
                "id": wid,
                "name": entry.get("name"),
                "latency_avg_ms": sum(recent) / len(recent) if recent else None,
                "sample_count": len(recent),
            }
        )
    return {"wan_count": len(order), "wans": wans}


def get_bandwidth_usage_client(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/status.bandwidthUsage.client")


def summarize_bandwidth_usage_client(data: dict[str, Any]) -> dict[str, Any]:
    periods = [k for k in ("hourly", "daily", "monthly", "billing") if k in data]
    return {"periods_available": periods, "period_count": len(periods)}


def get_wan_status(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/status.wan")


def summarize_wan_status(data: dict[str, Any]) -> dict[str, Any]:
    order = data.get("order", [])
    wans = []
    for wid in order:
        entry = data.get(str(wid), {})
        if not isinstance(entry, dict):
            continue
        wans.append(
            {
                "id": wid,
                "name": entry.get("name"),
                "enable": entry.get("enable"),
                "ip": entry.get("ip"),
                "gateway": entry.get("gateway"),
                "message": entry.get("message"),
                "status_led": entry.get("statusLed"),
                "method": entry.get("method"),
                "routing_mode": entry.get("routingMode"),
            }
        )
    return {"wan_count": len(wans), "wans": wans}


def get_lan_status(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/status.lan")


def summarize_lan_status(data: dict[str, Any]) -> dict[str, Any]:
    order = data.get("order", [])
    profiles = []
    for lid in order:
        entry = data.get(str(lid), {})
        if not isinstance(entry, dict):
            continue
        profiles.append(
            {
                "id": lid,
                "ip": entry.get("ip"),
                "mask": entry.get("mask"),
            }
        )
    return {"profile_count": len(profiles), "profiles": profiles}


def get_cpu_status(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/status.cpu")


def summarize_cpu_status(data: dict[str, Any]) -> dict[str, Any]:
    cpu = data.get("cpu") if isinstance(data.get("cpu"), dict) else {}
    return {"load": cpu.get("load")}
