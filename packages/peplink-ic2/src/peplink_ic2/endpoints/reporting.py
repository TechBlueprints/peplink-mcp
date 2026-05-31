"""InControl 2 reporting reads (bandwidth, event log)."""

from __future__ import annotations

from typing import Any

from peplink_ic2.client import IC2Client


def get_device_bandwidth(client: IC2Client, org_id: str, group_id: str, device_id: str) -> Any:
    return client.request(
        "GET", f"/rest/o/{org_id}/g/{group_id}/d/{device_id}/bandwidth"
    )


def get_org_bandwidth_per_device(client: IC2Client, org_id: str) -> Any:
    return client.request("GET", f"/rest/o/{org_id}/bandwidth_per_device")


def get_device_event_log(client: IC2Client, org_id: str, group_id: str, device_id: str) -> Any:
    return client.request(
        "GET", f"/rest/o/{org_id}/g/{group_id}/d/{device_id}/event_log"
    )


def summarize_event_log(data: Any, *, limit: int = 20) -> dict[str, Any]:
    rows: list[Any] = data if isinstance(data, list) else []
    if isinstance(data, dict):
        for key in ("events", "logs", "data", "list"):
            inner = data.get(key)
            if isinstance(inner, list):
                rows = inner
                break
    return {
        "total": len(rows),
        "returned": min(len(rows), limit),
        "truncated": len(rows) > limit,
        "events": rows[:limit],
    }
