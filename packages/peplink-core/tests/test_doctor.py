"""Doctor report aggregation tests."""

from unittest.mock import patch

from peplink_core.config import (
    ClientCredentialsAuth,
    DeviceAuthPair,
    DeviceConfig,
    FleetConfig,
)
from peplink_core.doctor import run_doctor


def test_doctor_success():
    fleet = FleetConfig(
        devices={
            "lab": DeviceConfig(
                host="192.168.50.1",
                auth=DeviceAuthPair(
                    read_only=ClientCredentialsAuth(
                        client_id="ro", client_secret="ro-secret"
                    ),
                    admin=ClientCredentialsAuth(
                        client_id="admin", client_secret="admin-secret"
                    ),
                ),
            )
        }
    )

    class FakeClient:
        def __init__(self, base_url, auth, tier, **kwargs):
            self.auth = auth
            self.tier = tier

        def ensure_authenticated(self):
            return None

        def ping(self):
            return {"order": [1]}

    with patch("peplink_core.registry.PeplinkDeviceClient", FakeClient):
        report = run_doctor("lab", fleet=fleet)

    assert report.ok
    assert len(report.tiers) == 2
    assert all(t.ok for t in report.tiers)
