"""Endpoint summarizer unit tests."""

from peplink_core.endpoints.config import (
    summarize_firewall_config,
    summarize_pepvpn_config,
    summarize_pepvpn_profile_config,
    summarize_port_config,
    summarize_snmp_info_config,
    summarize_ssid_profiles,
    summarize_wan_connection_config,
)
from peplink_core.endpoints.info import summarize_firmware, summarize_location
from peplink_core.endpoints.status import (
    summarize_clients,
    summarize_cpu_status,
    summarize_pepvpn,
    summarize_port_status,
    summarize_status_log,
    summarize_traffic,
    summarize_wan_connection,
    summarize_wan_status,
)


def test_summarize_location():
    out = summarize_location(
        {"location": {"latitude": 1.0, "longitude": 2.0, "speed": 0.0}}
    )
    assert out["fix"] is True
    assert out["latitude"] == 1.0


def test_summarize_wan():
    out = summarize_wan_connection(
        {
            "order": [1, 2],
            "1": {"name": "WAN1", "enable": True, "statusLed": "green", "message": "Connected"},
            "2": {"enable": False, "statusLed": "gray", "message": "Disabled"},
        }
    )
    assert out["wan_count"] == 2
    assert out["enabled_count"] == 1


def test_summarize_clients_truncation():
    items = [{"name": f"c{i}", "ip": f"10.0.0.{i}"} for i in range(100)]
    out = summarize_clients({"list": items}, limit=10)
    assert out["total_reported"] == 100
    assert out["returned"] == 10
    assert out["truncated"] is True


def test_summarize_firmware_in_use():
    out = summarize_firmware(
        {
            "1": {"version": "8.5.4 build 6264", "inUse": True},
            "2": {"version": "8.5.3 build 6030", "inUse": False},
        }
    )
    assert out["in_use"] == "8.5.4 build 6264"


def test_summarize_wan_config():
    out = summarize_wan_connection_config(
        {
            "order": [1],
            "1": {"name": "WAN1", "enable": True, "type": "ethernet", "priority": 1},
        }
    )
    assert out["profile_count"] == 1
    assert out["profiles"][0]["name"] == "WAN1"


def test_summarize_ssid_profiles():
    out = summarize_ssid_profiles(
        {
            "order": [10],
            "10": {"name": "Guest", "enable": True, "ssid": "Peplink-Guest"},
        }
    )
    assert out["profile_count"] == 1
    assert out["profiles"][0]["ssid"] == "Peplink-Guest"


def test_summarize_port_config():
    out = summarize_port_config(
        {
            "order": ["frontPanel", "switchA"],
            "frontPanel": {
                "order": [1],
                "1": {"port": {"order": ["lan_1", "lan_2"]}},
            },
            "switchA": {
                "order": [2],
                "2": {"port": {"order": ["1", "2", "3"]}},
            },
            "linkAggregation": {"order": [1]},
        }
    )
    assert out["module_count"] == 2
    assert out["modules"][0]["port_count"] == 2
    assert out["modules"][1]["port_count"] == 3
    assert out["link_aggregation_count"] == 1


def test_summarize_port_status():
    out = summarize_port_status(
        {
            "lan": {
                "order": [1, 2],
                "1": {"name": "LAN 1", "enable": True, "linkUp": True},
                "2": {"name": "LAN 2", "enable": True, "linkUp": False},
            },
            "wan": {"order": [1], "1": {"name": "WAN 1", "enable": True, "linkUp": True}},
        }
    )
    assert len(out["sections"]) == 2
    assert out["sections"][0]["port_count"] == 2


def test_summarize_traffic():
    out = summarize_traffic(
        {
            "bandwidth": {
                "unit": "kbps",
                "order": [1],
                "1": {"name": "WAN1", "overall": {"download": 100, "upload": 50}},
            },
            "traffic": {"unit": "MB"},
        }
    )
    assert out["stream_count"] == 1
    assert out["streams"][0]["name"] == "WAN1"


def test_summarize_status_log_truncation():
    out = summarize_status_log({"log": ["line"] * 5, "is_end_of_log": True}, limit=2)
    assert out["line_count"] == 5
    assert out["returned"] == 2
    assert out["truncated"] is True


def test_summarize_snmp_info_config():
    out = summarize_snmp_info_config(
        {"name": "peplink", "port": 161, "v1": {"enable": True}, "v2": {"enable": False}}
    )
    assert out["v1_enable"] is True
    assert out["port"] == 161


def test_summarize_pepvpn_profiles_and_peers():
    out = summarize_pepvpn(
        {
            "profile": {
                "order": [5],
                "siteId": "SITE-1",
                "5": {
                    "name": "conn_to_gateway",
                    "type": "l3",
                    "status": "CONNECTED",
                    "peerCount": 1,
                },
            },
            "peer": [
                {
                    "peerId": "5-1",
                    "profileId": 5,
                    "name": "gateway",
                    "status": "CONNECTED",
                    "serialNumber": "AAAA-1111-2222",
                    "route": ["192.0.2.0/24"],
                }
            ],
        }
    )
    assert out["site_id"] == "SITE-1"
    assert out["profile_count"] == 1
    assert out["profiles"][0]["name"] == "conn_to_gateway"
    assert out["peer_count"] == 1
    assert out["peers"][0]["routes"] == ["192.0.2.0/24"]


def test_summarize_pepvpn_config():
    out = summarize_pepvpn_config(
        {
            "siteId": "SITE-1",
            "healthcheck": {"mode": "0"},
            "reference": {
                "defaultSiteId": "hub-site",
                "reservedPort": {"order": [5500, 32015]},
            },
        }
    )
    assert out["site_id"] == "SITE-1"
    assert out["default_site_id"] == "hub-site"
    assert 5500 in out["reserved_ports"]


def test_summarize_pepvpn_profile_config_redacts_psk():
    out = summarize_pepvpn_profile_config(
        {
            "order": [5],
            "5": {
                "name": "conn_to_gateway",
                "enable": True,
                "encryption": "aes256",
                "authentication": {
                    "type": "psk",
                    "detail": [{"remoteId": "gateway.example", "psk": "secret-key"}],
                },
                "dataPort": {"protocol": {"port": 5500}},
                "wan": {"order": [1], "1": {"priority": 1}},
            },
        }
    )
    assert out["profile_count"] == 1
    peer = out["profiles"][0]["remote_peers"][0]
    assert peer["remote_id"] == "gateway.example"
    assert peer["psk"] == "[redacted]"


def test_summarize_firewall_config():
    out = summarize_firewall_config(
        {
            "outbound": {"policy": "allow", "rule": {"order": [1, 2]}},
            "inbound": {"policy": "deny", "rule": {"order": []}},
            "private": {"policy": "allow", "rule": {"order": [3]}},
            "localTraffic": False,
            "ids": True,
        }
    )
    assert out["outbound_rule_count"] == 2
    assert out["inbound_policy"] == "deny"
    assert out["ids_enabled"] is True


def test_summarize_wan_status():
    out = summarize_wan_status(
        {
            "order": [1],
            "1": {
                "name": "WAN",
                "enable": True,
                "ip": "192.0.2.20",
                "message": "Connected",
            },
        }
    )
    assert out["wan_count"] == 1
    assert out["wans"][0]["ip"] == "192.0.2.20"


def test_summarize_cpu_status():
    assert summarize_cpu_status({"cpu": {"load": "1.00%"}})["load"] == "1.00%"
