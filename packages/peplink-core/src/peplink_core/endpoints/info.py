"""Info endpoint helpers."""

from __future__ import annotations

from typing import Any

from peplink_core.client import PeplinkDeviceClient


def get_location(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/info.location")


def summarize_location(data: dict[str, Any]) -> dict[str, Any]:
    loc = data.get("location") if isinstance(data.get("location"), dict) else data
    if not isinstance(loc, dict):
        return {"fix": False}
    keys = (
        "latitude",
        "longitude",
        "altitude",
        "speed",
        "heading",
        "accuracy",
        "timestamp",
    )
    summary = {k: loc[k] for k in keys if loc.get(k) is not None}
    summary["fix"] = "latitude" in summary and "longitude" in summary
    return summary


def get_firmware(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/info.firmware")


def summarize_firmware(data: dict[str, Any]) -> dict[str, Any]:
    entries = []
    in_use = None
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        version = value.get("version")
        if not version:
            continue
        row = {"slot": key, "version": version, "inUse": bool(value.get("inUse"))}
        entries.append(row)
        if row["inUse"]:
            in_use = version
    return {"in_use": in_use, "entries": entries}
