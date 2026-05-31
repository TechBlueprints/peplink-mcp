"""IC2 config model + secrets-merge tests."""

from __future__ import annotations

import textwrap

import pytest
from peplink_core.config import (
    DeviceIC2Mapping,
    IC2Config,
    load_fleet_config,
)
from peplink_core.exceptions import PeplinkConfigError


def test_ic2_mapping_requires_serial_or_full_ids():
    DeviceIC2Mapping(serial="ABCD-1234")  # serial alone OK
    DeviceIC2Mapping(org_id="1", group_id="2", device_id="3")  # explicit OK
    with pytest.raises(ValueError):
        DeviceIC2Mapping(org_id="1")  # partial ids, no serial


def test_ic2_config_defaults_disabled():
    cfg = IC2Config()
    assert cfg.enabled is False
    assert cfg.base_url == "https://api.ic.peplink.com"
    assert cfg.auth is None
    assert cfg.has_any_auth is False


def test_single_auth_serves_both_tiers():
    from peplink_core.config import IC2ClientCredentials

    cfg = IC2Config(enabled=True, auth=IC2ClientCredentials(client_id="x", client_secret="y"))
    assert cfg.has_any_auth is True
    assert cfg.read_credentials().client_id == "x"
    assert cfg.write_credentials().client_id == "x"


def test_split_credentials_route_by_tier():
    from peplink_core.config import IC2ClientCredentials

    cfg = IC2Config(
        enabled=True,
        read_only=IC2ClientCredentials(client_id="ro", client_secret="s"),
        admin=IC2ClientCredentials(client_id="rw", client_secret="s"),
    )
    assert cfg.read_credentials().client_id == "ro"
    assert cfg.write_credentials().client_id == "rw"


def test_read_only_credential_cannot_write():
    from peplink_core.config import IC2ClientCredentials

    cfg = IC2Config(
        enabled=True, read_only=IC2ClientCredentials(client_id="ro", client_secret="s")
    )
    assert cfg.read_credentials().client_id == "ro"
    assert cfg.write_credentials() is None  # no write-capable credential


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(textwrap.dedent(text))
    return p


def test_load_merges_ic2_auth_and_device_mapping(tmp_path):
    cfg = _write(
        tmp_path,
        "config.yaml",
        """
        incontrol2:
          enabled: true
          default_org_id: "100"
        devices:
          gateway:
            host: 192.0.2.1
            kind: router
        """,
    )
    secrets = _write(
        tmp_path,
        "secrets.yaml",
        """
        incontrol2:
          auth:
            grant_type: client_credentials
            client_id: CID
            client_secret: CSECRET
        devices:
          gateway:
            auth:
              read_only:
                type: client_credentials
                client_id: ro
                client_secret: ro-secret
            ic2:
              serial: "1A2B-3C4D-5E6F"
        """,
    )

    fleet = load_fleet_config(cfg, secrets)
    assert fleet.ic2_enabled is True
    assert fleet.incontrol2.auth.client_id == "CID"
    assert fleet.incontrol2.default_org_id == "100"
    assert fleet.devices["gateway"].ic2.serial == "1A2B-3C4D-5E6F"
    assert fleet.devices["gateway"].config_authority == "auto"


def test_enabled_without_auth_is_an_error(tmp_path):
    cfg = _write(
        tmp_path,
        "config.yaml",
        """
        incontrol2:
          enabled: true
        devices:
          gateway:
            host: 192.0.2.1
            kind: router
        """,
    )
    secrets = _write(
        tmp_path,
        "secrets.yaml",
        """
        devices:
          gateway:
            auth:
              read_only:
                type: userpass
                username: rouser
                password: pw
        """,
    )
    with pytest.raises(PeplinkConfigError, match="incontrol2.enabled"):
        load_fleet_config(cfg, secrets)
