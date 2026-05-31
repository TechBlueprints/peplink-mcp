"""Generic Peplink HTTP API invocation helpers."""

from __future__ import annotations

import json
from typing import Any

from peplink_core.client import PeplinkDeviceClient
from peplink_core.exceptions import PeplinkConfigError


def parse_json_body(body: str | None) -> dict[str, Any]:
    if body is None or not str(body).strip() or str(body).strip() == "{}":
        return {}
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PeplinkConfigError(f"body must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise PeplinkConfigError("body must be a JSON object")
    return parsed


def parse_json_query(query: str | None) -> dict[str, Any]:
    if query is None or not str(query).strip():
        return {}
    try:
        parsed = json.loads(query)
    except json.JSONDecodeError as exc:
        raise PeplinkConfigError(f"query must be valid JSON object: {exc}") from exc
    if not isinstance(parsed, dict):
        raise PeplinkConfigError("query must be a JSON object")
    return parsed


def invoke_device_api(
    client: PeplinkDeviceClient,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    unauthenticated: bool = False,
) -> dict[str, Any]:
    if unauthenticated:
        return client.request_unauthenticated(method, path, json_body=json_body, query=query)
    return client.request(method, path, query=query, json_body=json_body)


def summarize_api_response(
    data: dict[str, Any],
    *,
    device_id: str,
    host: str,
    method: str,
    path: str,
    proxied_from: str | None = None,
    destructive: bool = False,
) -> dict[str, Any]:
    return {
        "device_id": device_id,
        "host": host,
        "proxied_from": proxied_from,
        "method": method,
        "path": path,
        "destructive": destructive,
        "response": data,
    }
