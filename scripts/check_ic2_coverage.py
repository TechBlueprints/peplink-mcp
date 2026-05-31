#!/usr/bin/env python3
"""Compare the InControl 2 manifest against registered peplink_ic2_* MCP tools.

Separate from check_api_coverage.py so the official Router API metric stays clean.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "apps/device/src/peplink_device_mcp/manifest/ic2-api.yaml"
DEVICE_SRC = ROOT / "apps/device/src"


def load_manifest() -> list[dict]:
    data = yaml.safe_load(MANIFEST.read_text())
    return data.get("endpoints", [])


def load_registered_ic2_tools() -> set[str]:
    sys.path.insert(0, str(DEVICE_SRC))
    from peplink_device_mcp.ic2_tools import IC2_REGISTERED_TOOLS

    return set(IC2_REGISTERED_TOOLS)


def main() -> int:
    if not MANIFEST.exists():
        print(f"IC2 manifest not found: {MANIFEST}", file=sys.stderr)
        return 1

    expected = load_manifest()
    registered = load_registered_ic2_tools()

    missing = [e["tool"] for e in expected if e.get("tool") and e["tool"] not in registered]
    # Tools registered but absent from the manifest (drift the other way).
    manifest_tools = {e["tool"] for e in expected if e.get("tool")}
    undocumented = sorted(registered - manifest_tools)

    total = len(expected)
    covered = total - len(missing)
    pct = (covered / total * 100) if total else 0.0
    print(f"InControl 2 API coverage: {covered}/{total} ({pct:.1f}%)")

    rc = 0
    if missing:
        print("\nManifest endpoints with no registered tool:")
        for name in sorted(missing):
            print(f"  - {name}")
        rc = 1
    if undocumented:
        print("\nRegistered IC2 tools missing from the manifest:")
        for name in undocumented:
            print(f"  - {name}")
        rc = 1
    if rc == 0:
        print("IC2 manifest and registered tools are in sync.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
