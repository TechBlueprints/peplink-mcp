"""Fleet -> IC2 device matcher tests."""

from __future__ import annotations

from peplink_ic2.automap import FleetHint, IC2Index, match_device

RECORDS = [
    {"id": "12", "sn": "AAAA-1111-2222", "lan_mac": "aa:bb:cc:dd:ee:01",
     "name": "gateway.example.net", "model": "Peplink MAX BR2 Pro",
     "group_id": "5", "group_name": "gateway"},
    {"id": "15", "sn": "DDDD-7777-8888", "lan_mac": "AA:BB:CC:00:00:15",
     "name": "switch-a.gateway.example.net",
     "model": "Peplink SD Switch Rugged, 8-Port", "group_id": "5", "group_name": "gateway"},
    {"id": "16", "sn": "CCCC-5555-6666", "lan_mac": "AA:BB:CC:00:00:16",
     "name": "switch-b.gateway.example.net",
     "model": "Peplink SD Switch Rugged, 8-Port", "group_id": "5", "group_name": "gateway"},
    {"id": "3", "sn": "BBBB-3333-4444", "lan_mac": "AA:BB:CC:00:00:03",
     "name": "ap-a.gateway.example.net",
     "model": "Pepwave AP One Rugged", "group_id": "5", "group_name": "gateway"},
]


def _index():
    return IC2Index.build(RECORDS, group_names={"5": "gateway"})


def test_match_by_serial_exact():
    r = match_device(FleetHint("gateway", serial="aaaa-1111-2222"), _index())
    assert r.confidence == "serial" and r.is_exact
    assert r.record["id"] == "12"
    assert _index().site_of(r.record) == "gateway"


def test_match_by_mac_exact_covers_switch():
    # No serial (switch) — match on MAC.
    r = match_device(FleetHint("sw", mac="aa-bb-cc-00-00-16"), _index())
    assert r.confidence == "mac" and r.record["id"] == "16"


def test_unique_model_name_match():
    r = match_device(FleetHint("ap", model="AP One Rugged", name="ap-a"), _index())
    assert r.confidence == "name" and r.record["id"] == "3"


def test_ambiguous_model_returns_candidates_no_pick():
    # Two 8-port switches, no distinguishing name -> ambiguous, no record.
    r = match_device(FleetHint("sw8", model="SD Switch Rugged, 8-Port"), _index())
    assert r.confidence == "ambiguous"
    assert r.record is None
    assert {c["id"] for c in r.candidates} == {"15", "16"}


def test_no_match():
    r = match_device(FleetHint("ghost", serial="ZZZZ-0000-0000"), _index())
    assert r.confidence == "none" and r.record is None


def test_serial_beats_everything():
    # serial wins even if name would be ambiguous
    r = match_device(
        FleetHint("sw", serial="CCCC-5555-6666", model="SD Switch Rugged, 8-Port"), _index()
    )
    assert r.confidence == "serial" and r.record["id"] == "16"
