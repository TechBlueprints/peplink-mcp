"""Tests for policy-flag gating and destructive confirmation."""

from __future__ import annotations

import pytest
from peplink_mcp_shared.policy import ConfirmationRequired, PolicyError, PolicyGate


def test_from_env_parses_truthy_flags():
    gate = PolicyGate.from_env(
        {
            "PEPLINK_POLICY_ALLOW_SYSTEM_REBOOT": "1",
            "PEPLINK_POLICY_ALLOW_WAN_DISABLE": "true",
            "PEPLINK_POLICY_ALLOW_SMS_SEND": "YES",
            "PEPLINK_POLICY_ALLOW_CONFIG_APPLY": "on",
            "PATH": "/usr/bin",  # ignored — wrong prefix
        }
    )
    assert gate.allowed == frozenset(
        {
            "PEPLINK_POLICY_ALLOW_SYSTEM_REBOOT",
            "PEPLINK_POLICY_ALLOW_WAN_DISABLE",
            "PEPLINK_POLICY_ALLOW_SMS_SEND",
            "PEPLINK_POLICY_ALLOW_CONFIG_APPLY",
        }
    )


def test_from_env_ignores_falsy_values():
    gate = PolicyGate.from_env(
        {
            "PEPLINK_POLICY_ALLOW_SYSTEM_REBOOT": "0",
            "PEPLINK_POLICY_ALLOW_WAN_DISABLE": "false",
            "PEPLINK_POLICY_ALLOW_SMS_SEND": "",
            "PEPLINK_POLICY_ALLOW_CONFIG_APPLY": "maybe",
        }
    )
    assert gate.allowed == frozenset()


def test_allows_ungated_tool_always_passes():
    gate = PolicyGate(frozenset())
    assert gate.allows(None)
    assert not gate.allows("PEPLINK_POLICY_ALLOW_SYSTEM_REBOOT")


def test_require_raises_when_not_enabled():
    gate = PolicyGate(frozenset())
    with pytest.raises(PolicyError, match="PEPLINK_POLICY_ALLOW_SYSTEM_REBOOT"):
        gate.require("PEPLINK_POLICY_ALLOW_SYSTEM_REBOOT", tool="peplink_post_cmd_system_reboot")


def test_require_passes_when_enabled():
    gate = PolicyGate(frozenset({"PEPLINK_POLICY_ALLOW_SYSTEM_REBOOT"}))
    gate.require("PEPLINK_POLICY_ALLOW_SYSTEM_REBOOT", tool="x")  # no raise
    gate.require(None, tool="x")  # no raise


def test_confirmation_required_message():
    exc = ConfirmationRequired("peplink_post_cmd_system_reboot", "POST /api/cmd.system.reboot")
    assert "confirm=true" in str(exc)
    assert "POST /api/cmd.system.reboot" in str(exc)
