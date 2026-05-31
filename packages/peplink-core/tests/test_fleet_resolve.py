"""Fleet host resolution tests."""

from unittest.mock import patch

from peplink_core.config import (
    DeviceAuthPair,
    DeviceConfig,
    DeviceDiscoveryConfig,
    FleetConfig,
    UserpassAuth,
)
from peplink_core.discovery import DiscoveredPeer
from peplink_core.fleet_resolve import resolve_discovered_hosts
from peplink_core.snmp.client import SnmpConfig


def test_resolve_discovered_hosts_sets_host():
    auth = UserpassAuth(username="u", password="p")
    pair = DeviceAuthPair(read_only=auth)
    fleet = FleetConfig(
        defaults={"device_id": "gw", "gateway_id": "gw"},
        devices={
            "gw": DeviceConfig(host="10.0.0.1", auth=pair),
            "ap1": DeviceConfig(
                discover=DeviceDiscoveryConfig(match={"name": "AP Office"}),
                kind="ap",
                auth=pair,
                snmp=SnmpConfig(community="public"),
            ),
        },
    )
    peers = [DiscoveredPeer(name="AP Office", host="10.0.0.50", mac="aa:bb:cc:dd:ee:01")]

    with patch("peplink_core.fleet_resolve.discover_lan_clients", return_value=peers):
        resolve_discovered_hosts(fleet)

    assert fleet.devices["ap1"].host == "10.0.0.50"


def test_resolve_discovered_switch_via_lan_clients():
    auth = UserpassAuth(username="rouser", password="p")
    pair = DeviceAuthPair(read_only=auth)
    fleet = FleetConfig(
        defaults={"device_id": "gw", "gateway_id": "gw"},
        devices={
            "gw": DeviceConfig(host="10.0.0.1", auth=pair),
            "sw": DeviceConfig(
                discover=DeviceDiscoveryConfig(
                    via="gw",
                    match={"name": "branch"},
                ),
                kind="switch",
                management="gateway",
                auth=pair,
            ),
        },
    )
    peers = [
        DiscoveredPeer(name="branch-switch", host="192.0.2.236", mac="aa:bb:cc:dd:ee:03")
    ]

    with patch("peplink_core.fleet_resolve.discover_lan_clients", return_value=peers):
        resolve_discovered_hosts(fleet)

    assert fleet.devices["sw"].host == "192.0.2.236"


def test_resolve_synergized_router_via_wan_status():
    auth = UserpassAuth(username="u", password="p")
    pair = DeviceAuthPair(read_only=auth)
    fleet = FleetConfig(
        defaults={"device_id": "gw", "gateway_id": "gw"},
        devices={
            "gw": DeviceConfig(host="192.0.2.1", auth=pair),
            "sd": DeviceConfig(
                discover=DeviceDiscoveryConfig(
                    via="gw",
                    match={"serial": "EEEE-9999-0000"},
                ),
                kind="router",
                management="gateway",
                auth=pair,
            ),
        },
    )
    peers = [
        DiscoveredPeer(
            name="EEEE-9999-0000",
            host="192.0.2.1",
            kind_hint="synergized_router",
            source="status.wan.connection",
        )
    ]

    with patch("peplink_core.fleet_resolve.discover_synergy_peers", return_value=peers):
        resolve_discovered_hosts(fleet)

    assert fleet.devices["sd"].host == "192.0.2.1"


def test_read_only_fleet_has_no_admin_tools():
    auth = UserpassAuth(username="u", password="p")
    fleet = FleetConfig(
        devices={
            "gw": DeviceConfig(
                host="10.0.0.1",
                auth=DeviceAuthPair(read_only=auth),
            )
        }
    )
    assert fleet.access_mode == "read_only"
    assert fleet.admin_tools_enabled is False
