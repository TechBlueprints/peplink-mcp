"""IC2 tool registration + write-gate tests (no network — gates fire first)."""

from __future__ import annotations

import textwrap

import pytest
from mcp.server.fastmcp import FastMCP
from peplink_core.config import load_fleet_config
from peplink_core.registry import DeviceRegistry
from peplink_device_mcp.ic2_tools import (
    IC2_DESTRUCTIVE_TOOLS,
    IC2_READ_TOOLS,
    IC2_REGISTERED_TOOLS,
    IC2_WRITE_TOOLS,
    POLICY_CONFIG_WRITE,
    POLICY_REBOOT,
    register_ic2_tools,
)
from peplink_mcp_shared.mcp_keys import McpAuthzError, Principal, set_principal
from peplink_mcp_shared.policy import ConfirmationRequired, PolicyError, PolicyGate


def _fleet(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        textwrap.dedent(
            """
            incontrol2:
              enabled: true
              default_org_id: "100"
            devices:
              gateway:
                host: 192.0.2.1
                kind: router
                ic2:
                  serial: "1A2B-3C4D"
              pinned:
                host: 192.0.2.2
                kind: router
                ic2:
                  org_id: "100"
                  group_id: "200"
                  device_id: "300"
            """
        )
    )
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text(
        textwrap.dedent(
            """
            incontrol2:
              auth:
                client_id: CID
                client_secret: CSECRET
            devices:
              gateway:
                auth: {read_only: {type: userpass, username: r, password: p}}
              pinned:
                auth: {read_only: {type: userpass, username: r, password: p}}
            """
        )
    )
    return load_fleet_config(cfg, secrets)


def _server(tmp_path):
    from peplink_mcp_shared.context import AppContext

    fleet = _fleet(tmp_path)
    ctx = AppContext(fleet=fleet, registry=DeviceRegistry(fleet))
    server = FastMCP("test")
    register_ic2_tools(server, ctx)
    return server, ctx


def _fn(server, name):
    return server._tool_manager.get_tool(name).fn


@pytest.fixture(autouse=True)
def _reset_principal():
    set_principal(None)
    yield
    set_principal(None)


def test_all_tools_register(tmp_path):
    server, _ = _server(tmp_path)
    names = {t.name for t in server._tool_manager.list_tools()}
    assert IC2_REGISTERED_TOOLS <= names
    assert len(IC2_REGISTERED_TOOLS) == len(IC2_READ_TOOLS) + len(IC2_WRITE_TOOLS) + len(
        IC2_DESTRUCTIVE_TOOLS
    )


def test_write_denied_without_admin_tier(tmp_path):
    server, _ = _server(tmp_path)
    set_principal(Principal("ro", "read_only", source="test"))
    with pytest.raises(McpAuthzError):
        _fn(server, "peplink_ic2_set_vlan_config")(
            body="{}", org_id="100", group_id="200", confirm=True
        )


def test_write_denied_without_policy_flag(tmp_path):
    server, ctx = _server(tmp_path)
    set_principal(Principal("ops", "admin", source="test"))
    ctx.policy = PolicyGate(frozenset())  # no flags enabled
    with pytest.raises(PolicyError):
        _fn(server, "peplink_ic2_set_vlan_config")(
            body="{}", org_id="100", group_id="200", confirm=True
        )


def test_write_requires_confirm(tmp_path):
    server, ctx = _server(tmp_path)
    set_principal(Principal("ops", "admin", source="test"))
    ctx.policy = PolicyGate(frozenset({POLICY_CONFIG_WRITE}))
    with pytest.raises(ConfirmationRequired):
        _fn(server, "peplink_ic2_set_vlan_config")(
            body="{}", org_id="100", group_id="200", confirm=False
        )


def test_destructive_needs_its_own_policy(tmp_path):
    server, ctx = _server(tmp_path)
    set_principal(Principal("ops", "admin", source="test"))
    # Config-write flag is set, but reboot needs its dedicated flag.
    ctx.policy = PolicyGate(frozenset({POLICY_CONFIG_WRITE}))
    with pytest.raises(PolicyError):
        _fn(server, "peplink_ic2_reboot_device")(device_id="pinned", confirm=True)


def test_destructive_requires_confirm_even_with_policy(tmp_path):
    server, ctx = _server(tmp_path)
    set_principal(Principal("ops", "admin", source="test"))
    ctx.policy = PolicyGate(frozenset({POLICY_REBOOT}))
    with pytest.raises(ConfirmationRequired):
        _fn(server, "peplink_ic2_reboot_device")(device_id="pinned", confirm=False)


def _read_only_server(tmp_path):
    """Fleet with only an incontrol2.read_only credential (no write-capable cred)."""
    from peplink_mcp_shared.context import AppContext

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        textwrap.dedent(
            """
            incontrol2: {enabled: true, default_org_id: "100"}
            devices:
              gateway: {host: 192.0.2.1, kind: router, ic2: {serial: "S-1"}}
            """
        )
    )
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text(
        textwrap.dedent(
            """
            incontrol2:
              read_only: {client_id: RO, client_secret: s}
            devices:
              gateway: {auth: {read_only: {type: userpass, username: r, password: p}}}
            """
        )
    )
    fleet = load_fleet_config(cfg, secrets)
    ctx = AppContext(fleet=fleet, registry=DeviceRegistry(fleet))
    server = FastMCP("test")
    register_ic2_tools(server, ctx)
    return server, ctx, fleet


def test_read_only_credential_blocks_writes(tmp_path):
    from peplink_core.exceptions import PeplinkConfigError

    server, ctx, fleet = _read_only_server(tmp_path)
    assert fleet.ic2_enabled is True  # read-only credential still enables IC2 (reads)
    set_principal(Principal("ops", "admin", source="test"))
    ctx.policy = PolicyGate(frozenset({POLICY_CONFIG_WRITE}))
    # Gates pass (admin + policy + confirm) but there is no write-capable credential.
    with pytest.raises(PeplinkConfigError, match="write-capable credential"):
        _fn(server, "peplink_ic2_set_vlan_config")(
            body="{}", org_id="100", group_id="200", confirm=True
        )
