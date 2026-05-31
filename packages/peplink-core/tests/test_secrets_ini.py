from pathlib import Path

import pytest
from peplink_core.config import ClientCredentialsAuth, UserpassAuth
from peplink_core.secrets_ini import (
    load_ic2_secrets,
    load_peplink_credentials,
    load_peplink_secrets,
)


def test_load_ic2_secrets_single_client(tmp_path: Path) -> None:
    path = tmp_path / "secrets.conf"
    path.write_text(
        """
[secrets]
peplink.host = 192.0.2.1
peplink.username = rouser
peplink.password = secret
peplink.incontrol2.client_id = CID
peplink.incontrol2.client_secret = CSECRET
peplink.incontrol2.default_org_id = ORG-1
"""
    )
    ic2 = load_ic2_secrets(path)
    assert ic2 is not None
    assert ic2.enabled is True
    assert ic2.default_org_id == "ORG-1"
    assert ic2.read_credentials().client_id == "CID"
    assert ic2.write_credentials().client_id == "CID"


def test_load_ic2_secrets_split_tiers(tmp_path: Path) -> None:
    path = tmp_path / "secrets.conf"
    path.write_text(
        """
[secrets]
peplink.host = 192.0.2.1
peplink.username = rouser
peplink.password = secret
peplink.ic2read_clientid = RO
peplink.ic2read_clientsecret = ROS
peplink.ic2admin_clientid = RW
peplink.ic2admin_clientsecret = RWS
"""
    )
    ic2 = load_ic2_secrets(path)
    assert ic2.read_credentials().client_id == "RO"
    assert ic2.write_credentials().client_id == "RW"


def test_load_ic2_secrets_ic2admin_spelling(tmp_path: Path) -> None:
    # Home-secrets style: peplink.ic2admin_clientid / clientsecret (admin tier).
    path = tmp_path / "secrets.conf"
    path.write_text(
        """
[secrets]
peplink.host = 192.0.2.1
peplink.username = rouser
peplink.password = secret
peplink.ic2admin = ops@example.com
peplink.ic2admin_password = ignored-web-login
peplink.ic2admin_clientid = CID
peplink.ic2admin_clientsecret = CSECRET
"""
    )
    ic2 = load_ic2_secrets(path)
    assert ic2 is not None and ic2.enabled is True
    # single admin client serves both read and write
    assert ic2.write_credentials().client_id == "CID"
    assert ic2.read_credentials().client_id == "CID"


def test_load_ic2_secrets_absent_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "secrets.conf"
    path.write_text("[secrets]\npeplink.host = 192.0.2.1\n")
    assert load_ic2_secrets(path) is None


def test_load_peplink_secrets_userpass(tmp_path: Path) -> None:
    path = tmp_path / "secrets.conf"
    path.write_text(
        """
[secrets]
peplink.host = 192.0.2.1
peplink.username = rouser
peplink.password = secret
peplink.admin_username = admin
peplink.admin_password = adminpass
"""
    )
    secrets = load_peplink_secrets(path)
    assert secrets.host == "192.0.2.1"
    assert isinstance(secrets.read_only, UserpassAuth)
    assert secrets.read_only.username == "rouser"
    assert isinstance(secrets.admin, UserpassAuth)
    assert secrets.admin.username == "admin"


def test_load_peplink_secrets_api_clients(tmp_path: Path) -> None:
    path = tmp_path / "secrets.conf"
    path.write_text(
        """
[secrets]
peplink.host = 192.0.2.1
peplink.readonly_api_client_id = status-id
peplink.readonly_api_client_secret = status-secret
peplink.config_read_api_client_id = config-id
peplink.config_read_api_client_secret = config-secret
peplink.admin_api_client_id = admin-id
peplink.admin_api_client_secret = admin-secret
"""
    )
    secrets = load_peplink_secrets(path)
    assert isinstance(secrets.read_only, ClientCredentialsAuth)
    assert secrets.read_only.client_id == "status-id"
    assert secrets.read_only.scope == "api.read-only"
    assert isinstance(secrets.config_read, ClientCredentialsAuth)
    assert secrets.config_read.client_id == "config-id"
    assert secrets.config_read.scope == "api"
    assert isinstance(secrets.admin, ClientCredentialsAuth)
    assert secrets.admin.client_id == "admin-id"
    assert secrets.admin.scope == "api"


def test_load_peplink_credentials_legacy(tmp_path: Path) -> None:
    path = tmp_path / "secrets.conf"
    path.write_text(
        """
[secrets]
peplink.host = 192.0.2.1
peplink.username = rouser
peplink.password = secret
"""
    )
    assert load_peplink_credentials(path) == ("192.0.2.1", "rouser", "secret")


def test_load_peplink_credentials_rejects_api_client(tmp_path: Path) -> None:
    path = tmp_path / "secrets.conf"
    path.write_text(
        """
[secrets]
peplink.host = 192.0.2.1
peplink.readonly_api_client_id = ro-id
peplink.readonly_api_client_secret = ro-secret
"""
    )
    with pytest.raises(ValueError, match="read-only API client configured"):
        load_peplink_credentials(path)


def test_load_peplink_fusionhub_secrets(tmp_path: Path) -> None:
    path = tmp_path / "secrets.conf"
    path.write_text(
        """
[secrets]
peplink.host = 192.0.2.1
peplink.username = rouser
peplink.password = secret
peplink.fusionhub.host = 192.0.2.10
peplink.fusionhub.username = rouser
peplink.fusionhub.password = fh-secret
peplink.fusionhub.admin_username = admin
peplink.fusionhub.admin_password = adminpass
"""
    )
    from peplink_core.secrets_ini import load_peplink_fusionhub_secrets

    fh = load_peplink_fusionhub_secrets(path)
    assert fh is not None
    assert fh.host == "192.0.2.10"
    assert isinstance(fh.read_only, UserpassAuth)
    assert fh.read_only.password == "fh-secret"
    assert isinstance(fh.admin, UserpassAuth)
