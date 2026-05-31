"""AP SNMP parsing tests."""

from peplink_core.snmp.ap import normalize_mac, parse_client_table
from peplink_core.snmp.client import SnmpVarbind


def test_normalize_mac_from_0x_prefix():
    assert normalize_mac("0x021122334455") == "02:11:22:33:44:55"


def test_parse_client_table_groups_rows():
    rows = [
        SnmpVarbind(
            oid="1.3.6.1.4.1.27662.200.1.1.6.1.1.1.2.0.1.0",
            value="0x021122334455",
        ),
        SnmpVarbind(
            oid="1.3.6.1.4.1.27662.200.1.1.6.1.1.1.3.0.1.0",
            value="192.0.2.80",
        ),
        SnmpVarbind(
            oid="1.3.6.1.4.1.27662.200.1.1.6.1.1.1.7.0.1.0",
            value=58,
        ),
        SnmpVarbind(
            oid="1.3.6.1.4.1.27662.200.1.1.6.1.1.1.2.0.1.1",
            value="0x02aabbccddee",
        ),
        SnmpVarbind(
            oid="1.3.6.1.4.1.27662.200.1.1.6.1.1.1.3.0.1.1",
            value="192.0.2.51",
        ),
    ]
    clients = parse_client_table(rows)
    assert len(clients) == 2
    assert clients[0]["ip"] == "192.0.2.51"
    assert clients[0]["mac"] == "02:AA:BB:CC:DD:EE"
    assert clients[1]["ip"] == "192.0.2.80"
    assert clients[1]["signal"] == 58
