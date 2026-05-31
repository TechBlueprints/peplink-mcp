"""Tool registration metadata."""

from __future__ import annotations

from typing import Any

REGISTERED_TOOLS: dict[str, dict[str, Any]] = {}


def register_tool_metadata(name: str, **meta: Any) -> None:
    REGISTERED_TOOLS[name] = meta
