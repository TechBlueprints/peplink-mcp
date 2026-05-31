"""Gateway-managed device routing tests."""

import pytest
from peplink_core.config import DeviceConfig, DeviceDiscoveryConfig, FleetConfig
from peplink_core.exceptions import PeplinkConfigError
from peplink_core.management import (
    assert_direct_write_allowed,
    is_gateway_managed,
    management_gateway_id,
    resolve_write_handle,
)
from peplink_core.registry import DeviceRegistry


def _fleet() -> FleetConfig:
    return FleetConfig.model_validate(
        {
            "defaults": {"device_id": "gw", "gateway_id": "gw"},
            "devices": {
                "gw": {
                    "host": "192.0.2.1",
                    "kind": "router",
                    "auth": {
                        "read_only": {
                            "type": "userpass",
                            "username": "ro",
                            "password": "secret",
                        },
                        "admin": {
                            "type": "userpass",
                            "username": "admin",
                            "password": "secret",
                        },
                    },
                },
                "sw": {
                    "host": "192.0.2.158",
                    "kind": "switch",
                    "management": "gateway",
                    "discover": {"via": "gw", "match": {"model": "SD Switch"}},
                    "auth": {
                        "read_only": {
                            "type": "userpass",
                            "username": "ro",
                            "password": "secret",
                        },
                        "admin": {
                            "type": "userpass",
                            "username": "admin",
                            "password": "secret",
                        },
                    },
                },
            },
        }
    )


def test_is_gateway_managed():
    direct = DeviceConfig(host="10.0.0.1", auth=None)
    managed = DeviceConfig(
        host="10.0.0.2",
        kind="switch",
        management="gateway",
        discover=DeviceDiscoveryConfig(match={"model": "x"}),
        auth=None,
    )
    assert is_gateway_managed(direct) is False
    assert is_gateway_managed(managed) is True


def test_management_gateway_id_uses_discover_via():
    fleet = _fleet()
    device = fleet.devices["sw"]
    assert management_gateway_id(device, fleet) == "gw"


def test_assert_direct_write_blocked_for_managed_switch():
    fleet = _fleet()
    device = fleet.devices["sw"]
    with pytest.raises(PeplinkConfigError, match="management=gateway"):
        assert_direct_write_allowed("sw", device, api_path="/api/config.port")


def test_resolve_write_handle_proxies_to_gateway():
    registry = DeviceRegistry(_fleet())
    handle, proxied_from = resolve_write_handle(
        registry, "sw", api_path="/api/config.port"
    )
    assert handle.device_id == "gw"
    assert proxied_from == "sw"


def test_resolve_write_handle_allows_gateway_direct():
    registry = DeviceRegistry(_fleet())
    handle, proxied_from = resolve_write_handle(
        registry, "gw", api_path="/api/config.port"
    )
    assert handle.device_id == "gw"
    assert proxied_from is None
