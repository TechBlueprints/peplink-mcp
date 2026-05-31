#!/usr/bin/env python3
"""Compare official endpoint manifest against registered MCP tools."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "apps/device/src/peplink_device_mcp/manifest/router-api-8.5.2.yaml"
DEVICE_SRC = ROOT / "apps/device/src"


def load_manifest() -> list[dict]:
    data = yaml.safe_load(MANIFEST.read_text())
    endpoints = data.get("endpoints", [])
    return [e for e in endpoints if not e.get("coverage_exempt")]


def load_registered_tool_names() -> set[str]:
    sys.path.insert(0, str(DEVICE_SRC))
    import peplink_device_mcp.tool_registry  # noqa: F401, WPS433
    from peplink_device_mcp.tool_registry import REGISTERED_TOOLS  # noqa: WPS433

    return set(REGISTERED_TOOLS.keys())


def main() -> int:
    if not MANIFEST.exists():
        print(f"manifest not found: {MANIFEST}", file=sys.stderr)
        return 1

    expected = load_manifest()
    registered = load_registered_tool_names()

    missing = []
    for entry in expected:
        tool_name = entry.get("tool")
        if tool_name and tool_name not in registered:
            missing.append(tool_name)

    total = len(expected)
    covered = total - len(missing)
    pct = (covered / total * 100) if total else 0.0

    print(f"Official API coverage: {covered}/{total} ({pct:.1f}%)")

    if missing:
        print("\nMissing tools:")
        for name in sorted(missing):
            print(f"  - {name}")
        return 1

    print("All official endpoints have registered tools.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
