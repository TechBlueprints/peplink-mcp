"""AP SNMP config table parsing tests."""

import pytest
from peplink_core.endpoints.config import summarize_ssid_profiles
from peplink_core.snmp.ap import (
    AP_WLAN_SSID_ADVANCED_TABLE,
    AP_WLAN_SSID_PROFILE_TABLE,
    fetch_ap_ssid_profile_config,
    parse_ssid_advanced_table,
    parse_ssid_profile_table,
)
from peplink_core.snmp.client import SnmpVarbind


def test_parse_ssid_profile_and_advanced_tables():
    profile_rows = [
        SnmpVarbind(oid=f"{AP_WLAN_SSID_PROFILE_TABLE}.4.0", value="test-ssid"),
        SnmpVarbind(oid=f"{AP_WLAN_SSID_PROFILE_TABLE}.5.0", value=1),
        SnmpVarbind(oid=f"{AP_WLAN_SSID_PROFILE_TABLE}.13.0", value=3),
    ]
    advanced_rows = [
        SnmpVarbind(oid=f"{AP_WLAN_SSID_ADVANCED_TABLE}.2.0", value=4),
        SnmpVarbind(oid=f"{AP_WLAN_SSID_ADVANCED_TABLE}.7.0", value=2),
        SnmpVarbind(oid=f"{AP_WLAN_SSID_ADVANCED_TABLE}.10.0", value="secret"),
    ]
    profiles = parse_ssid_profile_table(profile_rows, AP_WLAN_SSID_PROFILE_TABLE)
    advanced = parse_ssid_advanced_table(advanced_rows, AP_WLAN_SSID_ADVANCED_TABLE)
    profile = profiles["0"]
    adv = advanced["0"]
    assert profile["ssid"] == "test-ssid"
    assert profile["enable"] is True
    assert profile["security"] == "wpa2_personal"
    assert adv["vlan_id"] == 4
    assert adv["band"] == 2
    assert adv["passphrase"] == "[redacted]"


@pytest.mark.live
def test_fetch_ap_ssid_profile_config_live(ap_target):
    host, cfg = ap_target
    data = fetch_ap_ssid_profile_config(host, cfg)
    summary = summarize_ssid_profiles(data)
    assert summary["profile_count"] >= 1
    assert summary["profiles"][0]["ssid"]
