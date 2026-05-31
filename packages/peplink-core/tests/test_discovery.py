"""Discovery parsing and matching tests."""

import pytest
from peplink_core.discovery import (
    match_discovered_peer,
    parse_discovered_peers,
    parse_lan_clients,
    parse_synergy_peers,
)
from peplink_core.exceptions import PeplinkConfigError


def test_parse_mesh_and_link_nodes():
    mesh = {
        "order": [1],
        "1": {
            "meshId": "home-mesh",
            "peer": [{"name": "AP Office", "ip": "10.0.0.50", "mac": "aa:bb:cc:dd:ee:01"}],
        },
    }
    link = {
        "nodes": {
            "2": {"name": "Switch Garage", "ip": "10.0.0.51", "mac": "aa:bb:cc:dd:ee:02", "model": "SD Switch"},
        }
    }
    peers = parse_discovered_peers(mesh, link)
    assert len(peers) == 2
    assert peers[0].host == "10.0.0.50"
    assert peers[1].model == "SD Switch"


def test_match_discovered_peer_by_mac():
    from peplink_core.discovery import DiscoveredPeer

    peers = [
        DiscoveredPeer(name="A", host="10.0.0.1", mac="aa:bb:cc:dd:ee:01"),
        DiscoveredPeer(name="B", host="10.0.0.2", mac="11:22:33:44:55:66"),
    ]
    matched = match_discovered_peer(peers, {"mac": "11:22:33:44:55:66"}, device_id="dev")
    assert matched.host == "10.0.0.2"


def test_match_discovered_peer_not_found():
    from peplink_core.discovery import DiscoveredPeer

    with pytest.raises(PeplinkConfigError, match="no gateway peer matched"):
        match_discovered_peer(
            [DiscoveredPeer(name="A", host="10.0.0.1")],
            {"name": "missing"},
            device_id="dev",
        )


def test_parse_lan_clients_and_match_client_type():

    peers = parse_lan_clients(
        {
            "list": [
                {
                    "name": "ap-one-test",
                    "ip": "192.0.2.200",
                    "mac": "02:00:00:00:00:01",
                    "clientType": "18",
                    "active": True,
                },
                {
                    "name": "laptop",
                    "ip": "192.0.2.50",
                    "clientType": "11",
                    "active": True,
                },
            ]
        }
    )
    assert len(peers) == 2
    matched = match_discovered_peer(
        peers,
        {"client_type": "18", "name": "ap-one"},
        device_id="ap-one-rugged",
    )
    assert matched.host == "192.0.2.200"


def test_parse_synergy_peers_from_wan_status():
    wan = {
        "8": {
            "synergyLink": True,
            "message": "Connected to EEEE-9999-0000 (Synergy)",
        },
        "10": {
            "synergy": True,
            "name": "Cellular - EEEE-9999-0000",
        },
    }
    peers = parse_synergy_peers(wan, gateway_host="192.0.2.1")
    assert len(peers) == 1
    assert peers[0].name == "EEEE-9999-0000"
    assert peers[0].host == "192.0.2.1"
    assert peers[0].kind_hint == "synergized_router"


def test_match_discovered_peer_by_serial():
    from peplink_core.discovery import DiscoveredPeer

    peers = [
        DiscoveredPeer(name="EEEE-9999-0000", host="192.0.2.1", kind_hint="synergized_router"),
    ]
    matched = match_discovered_peer(peers, {"serial": "EEEE-9999-0000"}, device_id="max-transit")
    assert matched.host == "192.0.2.1"
