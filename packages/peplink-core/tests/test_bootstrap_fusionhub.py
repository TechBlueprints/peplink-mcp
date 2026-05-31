"""Bootstrap tests for optional home FusionHub from secrets.conf."""

from pathlib import Path

from peplink_core.bootstrap import fleet_from_secrets_conf
from peplink_core.config import UserpassAuth


def test_fleet_from_secrets_conf_includes_fusionhub(tmp_path: Path) -> None:
    path = tmp_path / "secrets.conf"
    path.write_text(
        """
[secrets]
peplink.host = 192.0.2.1
peplink.username = rouser
peplink.password = gw-secret
peplink.fusionhub.host = 192.0.2.10
peplink.fusionhub.username = rouser
peplink.fusionhub.password = fh-secret
peplink.fusionhub.admin_username = admin
peplink.fusionhub.admin_password = fh-admin
"""
    )
    fleet = fleet_from_secrets_conf(secrets_conf=path, device_id="gateway")
    assert set(fleet.devices) == {"gateway", "fusionhub"}
    fh = fleet.devices["fusionhub"]
    assert fh.host == "192.0.2.10"
    assert fh.kind == "fusionhub"
    assert fh.auth is not None
    assert isinstance(fh.auth.read_only, UserpassAuth)
    assert fh.auth.config_read is not None
    assert isinstance(fh.auth.config_read, UserpassAuth)
    assert fh.auth.config_read.username == "admin"
