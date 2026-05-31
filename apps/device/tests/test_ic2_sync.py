"""ic2-sync orchestration test with an injected fake IC2 client."""

from __future__ import annotations

import textwrap

import yaml
from peplink_device_mcp.ic2_sync import run_ic2_sync

IC2_DEVICES = [
    {"id": "12", "sn": "AAAA-1111-2222", "name": "gateway.x", "model": "MAX BR2 Pro",
     "group_id": "5", "group_name": "gateway"},
    {"id": "3", "sn": "BBBB-3333-4444", "name": "ap-a.x", "model": "AP One Rugged",
     "group_id": "5", "group_name": "gateway"},
]


class FakeIC2Client:
    def __init__(self, *args, **kwargs):
        pass

    def request(self, method, path, **kwargs):
        if path.endswith("/g"):
            return [{"id": "5", "name": "gateway"}]
        if path.endswith("/d"):
            return IC2_DEVICES
        if path == "/rest/o":
            return [{"id": "ORG-1"}]
        return []


def _cfg(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        textwrap.dedent(
            """
            incontrol2: {enabled: true, default_org_id: "ORG-1"}
            devices:
              gateway:
                host: 10.0.0.1
                kind: router
                ic2: {serial: "AAAA-1111-2222"}   # already mapped
              the-ap:
                discover: {via: gateway, match: {name: ap-a, model: "AP One Rugged"}}
                kind: ap
            """
        )
    )
    sec = tmp_path / "secrets.yaml"
    sec.write_text(
        textwrap.dedent(
            """
            incontrol2: {auth: {client_id: x, client_secret: y}}
            devices:
              gateway: {auth: {read_only: {type: userpass, username: u, password: p}}}
              the-ap: {snmp: {community: public}}
            """
        )
    )
    return cfg, sec


def test_ic2_sync_dry_run_matches(tmp_path, capsys):
    cfg, sec = _cfg(tmp_path)
    rc = run_ic2_sync(
        config_path=str(cfg), secrets_path=str(sec), write=False, client=FakeIC2Client()
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Matched 2/2" in out
    assert "gateway" in out and "the-ap" in out
    # site comes from the IC2 group name
    assert "gateway" in out


def test_ic2_sync_write_emits_synced_copy(tmp_path):
    cfg, sec = _cfg(tmp_path)
    rc = run_ic2_sync(
        config_path=str(cfg), secrets_path=str(sec), write=True, client=FakeIC2Client()
    )
    assert rc == 0
    synced = cfg.with_suffix(".synced.yaml")
    assert synced.exists()
    data = yaml.safe_load(synced.read_text())
    # the-ap (name/model matched) gains a serial + site; gateway gains a site
    assert data["devices"]["the-ap"]["ic2"]["serial"] == "BBBB-3333-4444"
    assert data["devices"]["the-ap"]["site"] == "gateway"
    assert data["devices"]["gateway"]["site"] == "gateway"
