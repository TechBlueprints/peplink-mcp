"""Config loading tests."""

from pathlib import Path

import pytest
import yaml
from peplink_core.config import load_fleet_config
from peplink_core.exceptions import PeplinkConfigError

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples" / "config"


def test_load_config_without_secrets_fails_auth(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
devices:
  lab:
    host: 10.0.0.1
"""
    )
    with pytest.raises(PeplinkConfigError):
        load_fleet_config(cfg, tmp_path / "missing.yaml")


def test_load_merged_config(tmp_path):
    cfg = tmp_path / "config.yaml"
    sec = tmp_path / "secrets.yaml"
    cfg.write_text(
        """
defaults:
  device_id: lab
devices:
  lab:
    host: 192.168.50.1
    kind: router
    kind: router
"""
    )
    sec.write_text(
        """
devices:
  lab:
    auth:
      read_only:
        type: client_credentials
        client_id: ro-id
        client_secret: ro-secret
      admin:
        type: client_credentials
        client_id: admin-id
        client_secret: admin-secret
"""
    )
    fleet = load_fleet_config(cfg, sec)
    assert fleet.defaults.device_id == "lab"
    device = fleet.devices["lab"]
    assert device.base_url == "https://192.168.50.1:443"
    assert device.auth is not None
    assert device.auth.read_only.client_id == "ro-id"


def test_site_grouping_and_gateway_inheritance(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "defaults: {gateway_id: gw}\n"
        "devices:\n"
        "  gw:\n"
        "    host: 10.0.0.1\n"
        "    kind: router\n"
        "    site: gateway\n"
        "  sw:\n"           # gateway-managed → inherits gw's site
        "    discover: {via: gw, match: {name: sw}}\n"
        "    kind: switch\n"
        "    management: gateway\n"
        "  home-hub:\n"
        "    host: 192.0.2.10\n"
        "    kind: fusionhub\n"
        "    site: home\n"
    )
    sec = tmp_path / "secrets.yaml"
    sec.write_text(
        "devices:\n"
        "  gw: {auth: {read_only: {type: userpass, username: u, password: p}}}\n"
        "  sw: {auth: {read_only: {type: userpass, username: u, password: p}}}\n"
        "  home-hub: {auth: {read_only: {type: userpass, username: u, password: p}}}\n"
    )
    fleet = load_fleet_config(cfg, sec)
    assert fleet.effective_site("gw") == "gateway"
    assert fleet.effective_site("sw") == "gateway"  # inherited from gw
    assert fleet.effective_site("home-hub") == "home"
    assert fleet.sites() == {"gateway": ["gw", "sw"], "home": ["home-hub"]}


def test_ic2_only_device_needs_no_lan_auth(tmp_path):
    # A device with just an ic2 mapping (no host/discover) is cloud-only and valid.
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "devices:\n"
        "  cloud-ap:\n"
        "    kind: ap\n"
        "    ic2:\n"
        "      serial: 'AAAA-BBBB-CCCC'\n"
    )
    sec = tmp_path / "secrets.yaml"
    sec.write_text("{}\n")
    fleet = load_fleet_config(cfg, sec)
    dev = fleet.devices["cloud-ap"]
    assert dev.is_ic2_only is True
    assert dev.auth is None and dev.snmp is None


def test_device_without_host_discover_or_ic2_is_invalid(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("devices:\n  bad:\n    kind: router\n")
    sec = tmp_path / "secrets.yaml"
    sec.write_text("{}\n")
    with pytest.raises(Exception):
        load_fleet_config(cfg, sec)


def test_example_config_requires_secrets():
    cfg = EXAMPLES / "config.yaml"
    sec = EXAMPLES / "secrets.yaml.example"
    fleet = load_fleet_config(cfg, sec)
    assert "gateway" in fleet.devices
    assert fleet.defaults.device_id == "gateway"
    # Matches the device list in examples/config/config.yaml.
    assert len(fleet.devices) == len(
        yaml.safe_load((EXAMPLES / "config.yaml").read_text())["devices"]
    )


def test_multi_device_different_auth_and_profiles(tmp_path):
    cfg = tmp_path / "config.yaml"
    sec = tmp_path / "secrets.yaml"
    cfg.write_text(
        """
defaults:
  device_id: router-a
devices:
  router-a:
    host: 10.0.0.1
    kind: router
  switch-b:
    host: 10.0.0.2
    kind: switch
  ap-c:
    host: 10.0.0.3
    kind: ap
"""
    )
    sec.write_text(
        """
auth_profiles:
  switch-login:
    read_only:
      type: userpass
      username: sw-ro
      password: sw-ro-pass
    admin:
      type: userpass
      username: sw-admin
      password: sw-admin-pass
devices:
  router-a:
    auth:
      read_only:
        type: client_credentials
        client_id: ro-a
        client_secret: secret-a
      admin:
        type: client_credentials
        client_id: admin-a
        client_secret: secret-admin-a
  switch-b:
    auth_profile: switch-login
  ap-c:
    auth:
      read_only:
        type: userpass
        username: ap-admin
        password: ap-pass
      admin:
        type: userpass
        username: ap-admin
        password: ap-pass
    snmp:
      community: public
"""
    )
    fleet = load_fleet_config(cfg, sec)
    assert fleet.devices["router-a"].auth.read_only.client_id == "ro-a"
    assert fleet.devices["switch-b"].auth.read_only.username == "sw-ro"
    assert fleet.devices["ap-c"].auth.admin.password == "ap-pass"


def test_read_only_auth_without_admin(tmp_path):
    cfg = tmp_path / "config.yaml"
    sec = tmp_path / "secrets.yaml"
    cfg.write_text(
        """
devices:
  gw:
    host: 10.0.0.1
"""
    )
    sec.write_text(
        """
devices:
  gw:
    auth:
      read_only:
        type: userpass
        username: ro
        password: secret
"""
    )
    fleet = load_fleet_config(cfg, sec)
    assert fleet.devices["gw"].auth.admin is None
    assert fleet.access_mode == "read_only"
    cfg = tmp_path / "config.yaml"
    sec = tmp_path / "secrets.yaml"
    cfg.write_text(
        """
devices:
  one:
    host: 10.0.0.1
  two:
    host: 10.0.0.2
"""
    )
    sec.write_text(
        """
devices:
  one:
    auth:
      read_only:
        type: userpass
        username: u
        password: p
      admin:
        type: userpass
        username: u
        password: p
"""
    )
    with pytest.raises(PeplinkConfigError, match="two"):
        load_fleet_config(cfg, sec)
