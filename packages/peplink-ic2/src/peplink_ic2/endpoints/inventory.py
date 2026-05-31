"""InControl 2 inventory reads: organizations, groups, devices."""

from __future__ import annotations

from typing import Any

from peplink_ic2.client import IC2Client

_NAME_KEYS = ("name", "title", "label")
_ID_KEYS = ("id", "device_id", "deviceId", "org_id", "group_id")
_SERIAL_KEYS = ("sn", "serial_number", "serialNumber", "serial")


def _records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("devices", "data", "list", "groups", "organizations"):
            inner = data.get(key)
            if isinstance(inner, list):
                return [r for r in inner if isinstance(r, dict)]
    return []


def _pick(record: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return None


# -- organizations --------------------------------------------------------


def list_orgs(client: IC2Client) -> Any:
    return client.request("GET", "/rest/o")


def get_org(client: IC2Client, org_id: str) -> Any:
    return client.request("GET", f"/rest/o/{org_id}")


def summarize_orgs(data: Any) -> dict[str, Any]:
    rows = [
        {"id": _pick(r, ("id", "org_id")), "name": _pick(r, _NAME_KEYS)}
        for r in _records(data)
    ]
    return {"count": len(rows), "orgs": rows}


# -- groups ---------------------------------------------------------------


def list_groups(client: IC2Client, org_id: str) -> Any:
    return client.request("GET", f"/rest/o/{org_id}/g")


def summarize_groups(data: Any) -> dict[str, Any]:
    rows = [
        {"id": _pick(r, ("id", "group_id")), "name": _pick(r, _NAME_KEYS)}
        for r in _records(data)
    ]
    return {"count": len(rows), "groups": rows}


# -- devices --------------------------------------------------------------


def list_devices(client: IC2Client, org_id: str, group_id: str | None = None) -> Any:
    if group_id:
        return client.request("GET", f"/rest/o/{org_id}/g/{group_id}/d")
    return client.request("GET", f"/rest/o/{org_id}/d")


def summarize_devices(data: Any, *, limit: int = 100) -> dict[str, Any]:
    records = _records(data)
    rows = []
    for r in records[:limit]:
        rows.append(
            {
                "id": _pick(r, ("id", "device_id")),
                "name": _pick(r, _NAME_KEYS),
                "serial": _pick(r, _SERIAL_KEYS),
                "product": _pick(r, ("product_name", "product", "model")),
                "online": r.get("status") or r.get("online"),
                "group_id": _pick(r, ("group_id", "groupId", "gid")),
            }
        )
    return {
        "total": len(records),
        "returned": len(rows),
        "truncated": len(records) > limit,
        "devices": rows,
    }


def get_device_detail(client: IC2Client, org_id: str, group_id: str, device_id: str) -> Any:
    return client.request("GET", f"/rest/o/{org_id}/g/{group_id}/d/{device_id}")


def summarize_device_detail(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"raw": data}
    keys = (
        "id",
        "name",
        "sn",
        "serial_number",
        "product_name",
        "product",
        "fw_ver",
        "firmware",
        "status",
        "online",
        "uptime",
        "ip",
        "wan_ip",
        "group_id",
        "location",
    )
    return {k: data[k] for k in keys if data.get(k) is not None}
