"""Doctor diagnostics for AP SNMP devices."""

from peplink_core.config import (
    DefaultsConfig,
    DeviceAuthPair,
    DeviceConfig,
    DeviceDiscoveryConfig,
    FleetConfig,
    UserpassAuth,
)
from peplink_core.discovery import DiscoveredPeer
from peplink_core.doctor import run_doctor
from peplink_core.snmp.client import SnmpConfig


def test_doctor_ap_snmp(monkeypatch):
    fleet = FleetConfig(
        devices={
            "ap1": DeviceConfig(
                host="10.0.0.200",
                kind="ap",
                snmp=SnmpConfig(community="public"),
            )
        }
    )

    monkeypatch.setattr(
        "peplink_core.doctor.probe_ap_snmp_read",
        lambda host, snmp: (True, "SNMP ok; firmware 3.6.3"),
    )
    monkeypatch.setattr(
        "peplink_core.doctor.probe_ap_snmp_config_read",
        lambda host, snmp: (True, "SNMP config ok; 1 SSID profile(s)"),
    )

    report = run_doctor("ap1", fleet=fleet)
    assert report.ok
    assert report.base_url == "snmp://10.0.0.200:161"
    assert len(report.tiers) == 2
    assert all(t.auth_type == "snmp" for t in report.tiers)


def test_doctor_ap_resolves_host_from_gateway(monkeypatch):
    fleet = FleetConfig(
        defaults=DefaultsConfig(gateway_id="gw"),
        devices={
            "gw": DeviceConfig(
                host="10.0.0.1",
                auth=DeviceAuthPair(read_only=UserpassAuth(username="u", password="p")),
            ),
            "ap1": DeviceConfig(
                discover=DeviceDiscoveryConfig(match={"name": "ap-one-test"}),
                kind="ap",
                snmp=SnmpConfig(community="public"),
            ),
        },
    )

    monkeypatch.setattr(
        "peplink_core.fleet_resolve.discover_lan_clients",
        lambda _client: [
            DiscoveredPeer(name="ap-one-test", host="10.0.0.200", model="18"),
        ],
    )
    monkeypatch.setattr(
        "peplink_core.doctor.probe_ap_snmp_read",
        lambda host, snmp: (True, "ok"),
    )
    monkeypatch.setattr(
        "peplink_core.doctor.probe_ap_snmp_config_read",
        lambda host, snmp: (True, "ok"),
    )

    report = run_doctor("ap1", fleet=fleet)
    assert report.host == "10.0.0.200"
    assert report.ok
