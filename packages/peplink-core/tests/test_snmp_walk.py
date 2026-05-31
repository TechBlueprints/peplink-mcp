"""SNMP walk boundary tests (live — needs a real AP via .env)."""

import pytest
from peplink_core.snmp.ap import AP_WLAN_SSID_PROFILE_TABLE
from peplink_core.snmp.client import SnmpSession


@pytest.mark.live
def test_snmp_walk_stops_at_table_boundary(ap_target):
    host, cfg = ap_target
    session = SnmpSession(host, cfg)
    rows = session.walk(AP_WLAN_SSID_PROFILE_TABLE)
    assert len(rows) <= 32
    prefix = AP_WLAN_SSID_PROFILE_TABLE.rstrip(".") + "."
    assert all(row.oid.startswith(prefix) for row in rows)
