"""Gate-ordering tests for admin/write manifest tools and peplink_invoke.

Covers the triple gate: admin tier -> policy flag -> destructive confirm, plus
the audit trail. Device I/O is monkeypatched — no live device required.
"""

from __future__ import annotations

import json

import pytest
from peplink_core.config import FleetConfig
from peplink_core.manifest import ManifestToolSpec
from peplink_core.registry import DeviceRegistry
from peplink_device_mcp import manifest_tools
from peplink_device_mcp.manifest_tools import _build_invoke_handler, _build_tool_handler
from peplink_mcp_shared.context import AppContext
from peplink_mcp_shared.mcp_keys import McpAuthzError, McpKeyStore, Principal, bind_principal
from peplink_mcp_shared.policy import ConfirmationRequired, PolicyError, PolicyGate

REBOOT = ManifestToolSpec(
    name="peplink_post_cmd_system_reboot",
    method="POST",
    path="/api/cmd.system.reboot",
    tier="admin",
    destructive=True,
    policy="PEPLINK_POLICY_ALLOW_SYSTEM_REBOOT",
    device_kinds=("router", "fusionhub", "switch", "ap"),
)


def _ctx(policy_allowed: frozenset[str] = frozenset()) -> AppContext:
    fleet = FleetConfig.model_validate(
        {
            "defaults": {"device_id": "lab"},
            "devices": {
                "lab": {
                    "host": "10.255.255.255",
                    "kind": "router",
                    "auth": {
                        "read_only": {
                            "type": "client_credentials",
                            "client_id": "ro",
                            "client_secret": "ro-secret",
                        },
                        "admin": {
                            "type": "client_credentials",
                            "client_id": "adm",
                            "client_secret": "adm-secret",
                        },
                    },
                }
            },
        }
    )
    return AppContext(
        fleet=fleet,
        registry=DeviceRegistry(fleet),
        key_store=McpKeyStore([]),
        policy=PolicyGate(policy_allowed),
    )


def _fake_invoke(monkeypatch):
    calls = []

    def fake(client, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"stat": "ok"}

    monkeypatch.setattr(manifest_tools, "invoke_device_api", fake)
    return calls


ADMIN = Principal("adm-key", "admin", source="test")
READONLY = Principal("ro-key", "read_only", source="test")


def test_read_only_denied_admin_tool():
    handler = _build_tool_handler(_ctx(), REBOOT)
    with bind_principal(READONLY):
        with pytest.raises(McpAuthzError):
            handler(confirm=True)


def test_policy_flag_blocks_when_disabled():
    handler = _build_tool_handler(_ctx(policy_allowed=frozenset()), REBOOT)
    with bind_principal(ADMIN):
        with pytest.raises(PolicyError, match="PEPLINK_POLICY_ALLOW_SYSTEM_REBOOT"):
            handler(confirm=True)


def test_confirm_required_when_policy_allowed():
    handler = _build_tool_handler(
        _ctx(policy_allowed=frozenset({"PEPLINK_POLICY_ALLOW_SYSTEM_REBOOT"})), REBOOT
    )
    with bind_principal(ADMIN):
        with pytest.raises(ConfirmationRequired):
            handler(confirm=False)


def test_all_gates_satisfied_executes(monkeypatch, caplog):
    calls = _fake_invoke(monkeypatch)
    handler = _build_tool_handler(
        _ctx(policy_allowed=frozenset({"PEPLINK_POLICY_ALLOW_SYSTEM_REBOOT"})), REBOOT
    )
    with bind_principal(ADMIN):
        with caplog.at_level("INFO", logger="peplink.audit"):
            out = handler(confirm=True)
    payload = json.loads(out)
    assert payload["method"] == "POST"
    assert payload["path"] == "/api/cmd.system.reboot"
    assert payload["destructive"] is True
    assert calls == [("POST", "/api/cmd.system.reboot", calls[0][2])]
    # audit trail records the allowed action with the caller key
    assert any("decision=allow" in r.message and "key=adm-key" in r.message for r in caplog.records)


def test_denial_is_audited(caplog):
    handler = _build_tool_handler(_ctx(), REBOOT)
    with bind_principal(ADMIN):
        with caplog.at_level("WARNING", logger="peplink.audit"):
            with pytest.raises(PolicyError):
                handler(confirm=True)
    assert any("decision=deny:PolicyError" in r.message for r in caplog.records)


def test_invoke_inherits_policy_and_confirm(monkeypatch):
    ctx = _ctx(policy_allowed=frozenset())
    invoke = _build_invoke_handler(ctx)
    with bind_principal(ADMIN):
        # matched destructive+policy endpoint -> policy gate applies via invoke
        with pytest.raises(PolicyError, match="PEPLINK_POLICY_ALLOW_SYSTEM_REBOOT"):
            invoke("POST", "/api/cmd.system.reboot", confirm=True)


def test_invoke_unmatched_write_requires_confirm(monkeypatch):
    _fake_invoke(monkeypatch)
    ctx = _ctx()
    invoke = _build_invoke_handler(ctx)
    with bind_principal(ADMIN):
        with pytest.raises(ConfirmationRequired):
            invoke("POST", "/api/config.somethingNew", confirm=False)


def test_invoke_write_denied_for_read_only():
    ctx = _ctx()
    invoke = _build_invoke_handler(ctx)
    with bind_principal(READONLY):
        with pytest.raises(McpAuthzError):
            invoke("POST", "/api/config.somethingNew", confirm=True)
