"""Pytest session setup.

- Loads a local ``.env`` (gitignored) so live integration tests can read their
  targets (e.g. ``PEPLINK_TEST_AP_HOST``) without hardcoding any device address.
- Provides the ``ap_target`` fixture, which skips a live test when no target is set.

Live tests are deselected by default (``addopts = -m "not live"`` in pyproject.toml);
run them with ``pytest -m live`` once ``.env`` points at real gear.
"""

from __future__ import annotations

import os
import pathlib

import pytest


def _load_dotenv() -> None:
    env = pathlib.Path(__file__).parent / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


@pytest.fixture
def ap_target():
    """(host, SnmpConfig) for a live AP, or skip if no .env target is configured."""
    host = os.environ.get("PEPLINK_TEST_AP_HOST")
    if not host:
        pytest.skip("set PEPLINK_TEST_AP_HOST in .env to run live SNMP tests")
    from peplink_core.snmp.client import SnmpConfig

    community = os.environ.get("PEPLINK_TEST_SNMP_COMMUNITY", "public")
    return host, SnmpConfig(community=community)
