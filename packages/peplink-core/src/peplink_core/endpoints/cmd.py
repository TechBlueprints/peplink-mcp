"""Command endpoint helpers (read-only probes)."""

from __future__ import annotations

from typing import Any

from peplink_core.client import PeplinkDeviceClient


def get_ap_cmd_support(client: PeplinkDeviceClient) -> dict[str, Any]:
    return client.request("GET", "/api/cmd.ap")


def summarize_ap_cmd_support(data: dict[str, Any]) -> dict[str, Any]:
    return {"ap_controller_supported": data.get("support")}
