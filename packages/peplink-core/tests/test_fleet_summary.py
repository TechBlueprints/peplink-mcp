"""Fleet summary tests."""

from peplink_core.config import (
    DeviceAuthPair,
    DeviceConfig,
    FleetConfig,
    UserpassAuth,
)
from peplink_core.fleet_summary import fleet_capabilities, fleet_device_summaries


def test_fleet_device_summaries_include_auth_types():
    auth = UserpassAuth(username="u", password="p")
    fleet = FleetConfig(
        defaults={"device_id": "a", "gateway_id": "a"},
        devices={
            "a": DeviceConfig(host="10.0.0.1", auth=DeviceAuthPair(read_only=auth)),
            "b": DeviceConfig(
                host="10.0.0.2",
                kind="switch",
                auth=DeviceAuthPair(read_only=auth, admin=auth),
            ),
        },
    )
    rows = fleet_device_summaries(fleet)
    caps = fleet_capabilities(fleet)
    assert len(rows) == 2
    assert rows[0]["default"] is True
    assert rows[0]["admin_configured"] is False
    assert rows[1]["admin_configured"] is True
    assert caps["access_mode"] == "full"
