"""Smoke tests for Phase 0 scaffold."""

from pathlib import Path

import yaml


def test_official_manifest_has_59_endpoints():
    manifest = Path("apps/device/src/peplink_device_mcp/manifest/router-api-8.5.2.yaml")
    data = yaml.safe_load(manifest.read_text())
    endpoints = [e for e in data["endpoints"] if not e.get("coverage_exempt")]
    assert data["official_count"] == 59
    assert len(endpoints) == 59


def test_cli_version():
    from peplink_device_mcp.main import main

    assert main(["version"]) == 0
