"""Register manifest-defined MCP tools (writes + coverage gaps)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from peplink_core.config_authority import plan_write_authority
from peplink_core.endpoints.api_call import (
    invoke_device_api,
    parse_json_body,
    parse_json_query,
    summarize_api_response,
)
from peplink_core.exceptions import PeplinkConfigError
from peplink_core.management import resolve_write_handle
from peplink_core.manifest import ManifestToolSpec, load_manifest_tool_specs
from peplink_core.registry import DeviceHandle
from peplink_mcp_shared.audit import record_action
from peplink_mcp_shared.context import AppContext
from peplink_mcp_shared.policy import ConfirmationRequired

logger = logging.getLogger(__name__)

_WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

# Hand-written in runtime.py — do not register twice.
RUNTIME_REGISTERED_TOOLS: frozenset[str] = frozenset(
    {
        "peplink_whoami",
        "peplink_list_devices",
        "peplink_discover_mesh_devices",
        "peplink_discover_lan_clients",
        "peplink_discover_synergy_devices",
        "peplink_get_status_wan_connection",
        "peplink_get_info_location",
        "peplink_get_info_firmware",
        "peplink_get_status_pepvpn",
        "peplink_get_config_pepvpn",
        "peplink_get_config_pepvpn_profile",
        "peplink_get_status_client",
        "peplink_get_status_lan_profile",
        "peplink_get_status_wan_connection_allowance",
        "peplink_get_status_extap_mesh",
        "peplink_get_status_extap_mesh_link",
        "peplink_get_config_wan_connection",
        "peplink_get_config_mesh",
        "peplink_get_config_ssid_profile",
        "peplink_get_config_port",
        "peplink_get_status_port",
        "peplink_get_status_device",
        "peplink_get_status_wlan",
        "peplink_supplemental_get_status_traffic",
        "peplink_supplemental_get_status_log",
        "peplink_supplemental_get_status_wan_latency",
        "peplink_supplemental_get_status_bandwidth_usage_client",
        "peplink_supplemental_get_config_admin",
        "peplink_supplemental_get_config_incontrol",
        "peplink_supplemental_get_config_lan",
        "peplink_supplemental_get_config_snmp_info",
        "peplink_supplemental_get_config_firewall",
        "peplink_supplemental_get_config_nat_mapping",
        "peplink_supplemental_get_config_dhcp",
        "peplink_supplemental_get_config_dns",
        "peplink_supplemental_get_config_schedule",
        "peplink_supplemental_get_config_wan",
        "peplink_get_config_gpio",
        "peplink_get_config_wan_connection_priority",
        "peplink_supplemental_get_status_wan",
        "peplink_supplemental_get_status_lan",
        "peplink_supplemental_get_status_cpu",
        "peplink_get_cmd_ap",
        "peplink_get_cmd_ap_support",
        "peplink_snmp_get_ap_device_status",
        "peplink_snmp_get_ap_wlan_summary",
        "peplink_snmp_get_ap_wlan_clients",
        "peplink_doctor",
    }
)

_WRITE_PREFIXES = ("/api/config.", "/api/cmd.", "/api/status.")
_UNAUTH_PATHS = {"/api/login"}


def load_all_manifest_specs() -> list[ManifestToolSpec]:
    manifest_dir = Path(__file__).resolve().parent / "manifest"
    return load_manifest_tool_specs(
        manifest_dir / "router-api-8.5.2.yaml",
        manifest_dir / "supplemental.yaml",
    )


def _assert_device_kind(handle: DeviceHandle, spec: ManifestToolSpec) -> None:
    if spec.device_kinds and handle.config.kind not in spec.device_kinds:
        raise PeplinkConfigError(
            f"devices.{handle.device_id} kind={handle.config.kind} is not supported for "
            f"{spec.name} (allowed: {', '.join(spec.device_kinds)})"
        )


def _device_client_for_spec(handle: DeviceHandle, spec: ManifestToolSpec):
    if spec.tier == "admin":
        if handle.admin is None:
            raise PeplinkConfigError(
                f"devices.{handle.device_id}: admin credentials not configured "
                "(read-only fleet mode)"
            )
        return handle.admin
    if spec.tier == "config_read":
        if handle.config_read is not None:
            return handle.config_read
        if handle.admin is not None:
            return handle.admin
        raise PeplinkConfigError(
            f"devices.{handle.device_id}: config_read credentials not configured"
        )
    if spec.path.startswith("/api/config.") or spec.path.startswith("/api/cmd."):
        if handle.config_read is not None:
            return handle.config_read
    return handle.read_only


def _resolve_handle(
    ctx: AppContext,
    device_id: str | None,
    spec: ManifestToolSpec,
    *,
    override: str | None = None,
):
    is_write = spec.method in ("POST", "PUT", "PATCH", "DELETE")
    if is_write and (
        spec.path.startswith(_WRITE_PREFIXES) or spec.path.startswith("/api/config.")
    ):
        # Config-authority precedence (ic2 > gateway > device) with break-glass override.
        # Raises ConfigAuthorityRedirect when InControl 2 should handle this write.
        _, device = ctx.fleet.get_device(device_id)
        plan = plan_write_authority(
            device, spec.path, ic2_enabled=ctx.fleet.ic2_enabled, override=override
        )
        if plan.level == "gateway":
            handle, proxied = resolve_write_handle(ctx.registry, device_id, api_path=spec.path)
        else:  # direct device (default, or break-glass down from ic2/gateway)
            handle = ctx.resolve_device(device_id)
            proxied = None
    else:
        handle = ctx.resolve_device(device_id)
        proxied = None
    _assert_device_kind(handle, spec)
    return handle, proxied


def _mcp_tier_for_spec(spec: ManifestToolSpec) -> str:
    if spec.method in ("POST", "PUT", "PATCH", "DELETE"):
        return "admin"
    if spec.tier == "admin":
        return "admin"
    return "read_only"


def _audit_device(ctx: AppContext, device_id: str | None) -> str:
    return device_id or ctx.fleet.defaults.device_id or "<default>"


def _run_gates(
    ctx: AppContext,
    *,
    tool: str,
    method: str,
    path: str,
    device_id: str | None,
    required_tier: str,
    policy_key: str | None,
    destructive: bool,
    confirm: bool,
) -> None:
    """Tier -> policy -> confirm, in that order. Audits any denial, then re-raises."""
    principal = ctx.current_principal()
    try:
        ctx.require_tier(required_tier)  # type: ignore[arg-type]
        ctx.require_policy(policy_key, tool=tool)
        if destructive and not confirm:
            raise ConfirmationRequired(tool, f"{method} {path}")
    except Exception as exc:
        record_action(
            principal,
            tool=tool,
            method=method,
            path=path,
            device_id=_audit_device(ctx, device_id),
            decision=f"deny:{type(exc).__name__}",
            detail=str(exc),
        )
        raise


def _build_tool_handler(ctx: AppContext, spec: ManifestToolSpec) -> Callable[..., str]:
    required_mcp_tier = _mcp_tier_for_spec(spec)
    is_privileged = required_mcp_tier == "admin"

    def handler(
        device_id: str | None = None,
        body: str = "{}",
        query: str | None = None,
        confirm: bool = False,
        override: str | None = None,
    ) -> str:
        _run_gates(
            ctx,
            tool=spec.name,
            method=spec.method,
            path=spec.path,
            device_id=device_id,
            required_tier=required_mcp_tier,
            policy_key=spec.policy,
            destructive=spec.destructive,
            confirm=confirm,
        )

        if spec.method == "TCP":
            raise PeplinkConfigError(f"{spec.name}: TCP transport is not implemented")
        if spec.method == "SNMP":
            raise PeplinkConfigError(f"{spec.name}: use the SNMP-specific MCP tools for AP devices")
        if spec.method == "ANY":
            raise PeplinkConfigError(
                f"{spec.name}: use method and path parameters on peplink_invoke instead"
            )

        handle, proxied = _resolve_handle(ctx, device_id, spec, override=override)
        client = _device_client_for_spec(handle, spec)
        merged_query: dict[str, Any] = dict(spec.query)
        merged_query.update(parse_json_query(query))
        json_body = parse_json_body(body) if spec.method == "POST" else None
        unauthenticated = spec.path in _UNAUTH_PATHS

        if is_privileged:
            record_action(
                ctx.current_principal(),
                tool=spec.name,
                method=spec.method,
                path=spec.path,
                device_id=handle.device_id,
                decision="allow",
            )

        data = invoke_device_api(
            client,
            spec.method,
            spec.path,
            json_body=json_body,
            query=merged_query or None,
            unauthenticated=unauthenticated,
        )
        payload = summarize_api_response(
            data if isinstance(data, dict) else {"result": data},
            device_id=handle.device_id,
            host=handle.config.host or "",
            method=spec.method,
            path=spec.path,
            proxied_from=proxied,
            destructive=spec.destructive,
        )
        return json.dumps(payload, indent=2, default=str)

    handler.__name__ = spec.name
    gate_notes = []
    if spec.destructive:
        gate_notes.append("destructive: pass confirm=true")
    if spec.policy:
        gate_notes.append(f"requires {spec.policy}=1 in server env")
    suffix = f" ({'; '.join(gate_notes)})" if gate_notes else ""
    is_write = spec.method in _WRITE_METHODS
    override_note = (
        " If InControl 2 manages this config for the device, the call is redirected to "
        "the peplink_ic2_* tool; pass override='gateway' or override='device' to break "
        "the glass and write here anyway."
        if is_write
        else ""
    )
    handler.__doc__ = (
        f"{spec.method} {spec.path} (Peplink manifest tool). "
        f"Pass request JSON as `body`; optional extra query keys as JSON `query`. "
        f"Device tier: {spec.tier}.{suffix}{override_note}"
    )
    return handler


def _build_invoke_handler(ctx: AppContext) -> Callable[..., str]:
    # (method, path) -> spec so the escape hatch inherits the same policy/confirm
    # gates as the typed tool for that endpoint.
    spec_index: dict[tuple[str, str], ManifestToolSpec] = {
        (s.method, s.path): s for s in load_all_manifest_specs() if not s.coverage_exempt
    }

    def peplink_invoke(
        method: str,
        path: str,
        device_id: str | None = None,
        body: str = "{}",
        query: str | None = None,
        mcp_tier: str = "admin",
        confirm: bool = False,
        override: str | None = None,
    ) -> str:
        method_upper = method.upper()
        is_write = path.startswith(_WRITE_PREFIXES) or method_upper in _WRITE_METHODS
        requested = mcp_tier if mcp_tier in ("read_only", "admin") else "admin"
        required_tier = "admin" if is_write else requested

        matched = spec_index.get((method_upper, path))
        policy_key = matched.policy if matched else None
        # Matched destructive endpoints inherit their confirm requirement; an
        # unmatched write through the escape hatch is treated as destructive too.
        destructive = matched.destructive if matched else is_write

        _run_gates(
            ctx,
            tool="peplink_invoke",
            method=method_upper,
            path=path,
            device_id=device_id,
            required_tier=required_tier,
            policy_key=policy_key,
            destructive=destructive,
            confirm=confirm,
        )

        if is_write:
            _, device = ctx.fleet.get_device(device_id)
            plan = plan_write_authority(
                device, path, ic2_enabled=ctx.fleet.ic2_enabled, override=override
            )
            if plan.level == "gateway":
                handle, proxied = resolve_write_handle(ctx.registry, device_id, api_path=path)
            else:
                handle = ctx.resolve_device(device_id)
                proxied = None
        else:
            handle = ctx.resolve_device(device_id)
            proxied = None

        if handle.admin is None and (
            method_upper != "GET"
            or path.startswith("/api/config.")
            or path.startswith("/api/cmd.")
        ):
            if handle.config_read is None and required_tier == "admin":
                raise PeplinkConfigError(
                    f"devices.{handle.device_id}: elevated device credentials not configured"
                )

        if method_upper in _WRITE_METHODS:
            client = handle.admin or handle.config_read
        elif path.startswith("/api/config.") or path.startswith("/api/cmd."):
            client = handle.config_read or handle.admin or handle.read_only
        else:
            client = handle.read_only

        if client is None:
            raise PeplinkConfigError(f"devices.{handle.device_id}: no suitable credentials")

        if required_tier == "admin":
            record_action(
                ctx.current_principal(),
                tool="peplink_invoke",
                method=method_upper,
                path=path,
                device_id=handle.device_id,
                decision="allow",
            )

        data = invoke_device_api(
            client,
            method_upper,
            path,
            json_body=parse_json_body(body) if method_upper != "GET" else None,
            query=parse_json_query(query) or None,
            unauthenticated=path in _UNAUTH_PATHS,
        )
        payload = summarize_api_response(
            data if isinstance(data, dict) else {"result": data},
            device_id=handle.device_id,
            host=handle.config.host or "",
            method=method_upper,
            path=path,
            proxied_from=proxied,
        )
        return json.dumps(payload, indent=2, default=str)

    peplink_invoke.__doc__ = (
        "Call any Peplink HTTP path (escape hatch). Writes require admin MCP tier and "
        "the same policy flags / confirm=true as the typed tool for that endpoint; an "
        "unrecognized write path also requires confirm=true. `body` and `query` are "
        "JSON objects."
    )
    return peplink_invoke


def register_manifest_tools(
    server: FastMCP,
    ctx: AppContext,
    *,
    skip: frozenset[str] | None = None,
) -> list[str]:
    """Register manifest tools not already defined in runtime.py. Returns registered names."""
    skip_set = skip or RUNTIME_REGISTERED_TOOLS
    registered: list[str] = []
    skipped_writes = 0

    for spec in load_all_manifest_specs():
        if spec.coverage_exempt and spec.name == "peplink_invoke":
            server.tool(name=spec.name)(_build_invoke_handler(ctx))
            registered.append(spec.name)
            continue
        if spec.coverage_exempt:
            continue
        if spec.name in skip_set:
            continue
        is_write = spec.method in ("POST", "PUT", "PATCH", "DELETE")
        if is_write and not ctx.fleet.admin_tools_enabled:
            skipped_writes += 1
            continue
        handler = _build_tool_handler(ctx, spec)
        server.tool(name=spec.name)(handler)
        registered.append(spec.name)

    if registered:
        logger.info("Registered %d manifest MCP tools", len(registered))
    if skipped_writes:
        logger.info(
            "Skipped %d write manifest tools (configure auth.admin on at least one device)",
            skipped_writes,
        )
    return registered
