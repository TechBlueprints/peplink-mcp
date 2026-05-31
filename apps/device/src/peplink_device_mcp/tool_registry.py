# MCP tool metadata — synced with manifest YAML + hand-written runtime tools.
from __future__ import annotations

from pathlib import Path

from peplink_core.manifest import load_manifest_tool_specs
from peplink_mcp_shared.tool_registry import REGISTERED_TOOLS, register_tool_metadata

from peplink_device_mcp.ic2_tools import (
    IC2_DESTRUCTIVE_TOOLS,
    IC2_READ_TOOLS,
    IC2_WRITE_TOOLS,
)
from peplink_device_mcp.manifest_tools import RUNTIME_REGISTERED_TOOLS

_MANIFEST_DIR = Path(__file__).resolve().parent / "manifest"
_MANIFEST_SPECS = load_manifest_tool_specs(
    _MANIFEST_DIR / "router-api-8.5.2.yaml",
    _MANIFEST_DIR / "supplemental.yaml",
)

IMPLEMENTED_READ_TOOLS = sorted(RUNTIME_REGISTERED_TOOLS)

for _tool in IMPLEMENTED_READ_TOOLS:
    register_tool_metadata(_tool, tier="read_only", implemented=True, active=True)

_MANIFEST_REGISTERED: set[str] = set()
for _spec in _MANIFEST_SPECS:
    if _spec.coverage_exempt:
        continue
    if _spec.name in RUNTIME_REGISTERED_TOOLS:
        continue
    _MANIFEST_REGISTERED.add(_spec.name)
    _mcp_tier = (
        "admin"
        if _spec.method in ("POST", "PUT", "PATCH", "DELETE") or _spec.tier == "admin"
        else "read_only"
    )
    register_tool_metadata(_spec.name, tier=_mcp_tier, implemented=True, active=True)

register_tool_metadata("peplink_invoke", tier="admin", implemented=True, active=True)

for _tool in sorted(IC2_READ_TOOLS):
    register_tool_metadata(_tool, tier="read_only", implemented=True, active=True)
for _tool in sorted(IC2_WRITE_TOOLS | IC2_DESTRUCTIVE_TOOLS):
    register_tool_metadata(_tool, tier="admin", implemented=True, active=True)

IC2_TOOLS = sorted(IC2_READ_TOOLS | IC2_WRITE_TOOLS | IC2_DESTRUCTIVE_TOOLS)

IMPLEMENTED_TOOLS = sorted(
    set(IMPLEMENTED_READ_TOOLS) | _MANIFEST_REGISTERED | set(IC2_TOOLS) | {"peplink_invoke"}
)

PLANNED_SUPPLEMENTAL_TOOLS: list[str] = []

PLANNED_ADMIN_TOOLS: list[str] = []

__all__ = [
    "REGISTERED_TOOLS",
    "IMPLEMENTED_TOOLS",
    "IMPLEMENTED_READ_TOOLS",
    "PLANNED_ADMIN_TOOLS",
    "PLANNED_SUPPLEMENTAL_TOOLS",
    "register_tool_metadata",
]
