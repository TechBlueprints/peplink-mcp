"""Device write path honors IC2 precedence + break-glass override (no network)."""

from __future__ import annotations

import textwrap

import pytest
from peplink_core.config import load_fleet_config
from peplink_core.config_authority import ConfigAuthorityRedirect
from peplink_core.registry import DeviceRegistry
from peplink_device_mcp.manifest_tools import _resolve_handle, load_all_manifest_specs
from peplink_mcp_shared.context import AppContext


def _spec(name):
    for s in load_all_manifest_specs():
        if s.name == name:
            return s
    raise AssertionError(f"spec {name} not found")


def _ctx(tmp_path, *, ic2_enabled=True, config_authority="auto"):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""
            incontrol2:
              enabled: {str(ic2_enabled).lower()}
              default_org_id: "100"
            devices:
              gateway:
                host: 192.0.2.1
                kind: router
                config_authority: {config_authority}
                ic2:
                  serial: "S-1"
            """
        )
    )
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text(
        textwrap.dedent(
            """
            incontrol2:
              auth: {client_id: CID, client_secret: CSECRET}
            devices:
              gateway:
                auth:
                  read_only: {type: userpass, username: r, password: p}
                  admin: {type: userpass, username: a, password: p}
            """
        )
    )
    fleet = load_fleet_config(cfg, secrets)
    return AppContext(fleet=fleet, registry=DeviceRegistry(fleet))


def test_ic2_managed_write_redirects_without_override(tmp_path):
    ctx = _ctx(tmp_path)
    spec = _spec("peplink_post_config_ssid_profile")  # /api/config.ssid.profile
    with pytest.raises(ConfigAuthorityRedirect) as exc:
        _resolve_handle(ctx, "gateway", spec, override=None)
    assert exc.value.ic2_tool == "peplink_ic2_put_ssid_settings"


def test_break_glass_to_device_resolves_handle(tmp_path):
    ctx = _ctx(tmp_path)
    spec = _spec("peplink_post_config_ssid_profile")
    handle, proxied = _resolve_handle(ctx, "gateway", spec, override="device")
    assert handle.device_id == "gateway"
    assert proxied is None


def test_pinned_device_authority_skips_ic2(tmp_path):
    ctx = _ctx(tmp_path, config_authority="device")
    spec = _spec("peplink_post_config_ssid_profile")
    # config_authority=device → no redirect, writes go straight to the device.
    handle, _ = _resolve_handle(ctx, "gateway", spec, override=None)
    assert handle.device_id == "gateway"


def test_non_ic2_path_unaffected(tmp_path):
    ctx = _ctx(tmp_path)
    # A write path with no IC2 equivalent is not redirected.
    spec = _spec("peplink_post_config_gpio")  # /api/config.gpio
    handle, _ = _resolve_handle(ctx, "gateway", spec, override=None)
    assert handle.device_id == "gateway"
