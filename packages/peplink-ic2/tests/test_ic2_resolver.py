"""IC2 device→identity resolver tests."""

from __future__ import annotations

import httpx
import pytest
from peplink_core.config import DeviceIC2Mapping
from peplink_ic2.client import IC2Client
from peplink_ic2.exceptions import IC2ConfigError
from peplink_ic2.resolver import IC2Target, resolve_ic2_target


def _creds():
    from peplink_core.config import IC2ClientCredentials

    return IC2ClientCredentials(client_id="cid", client_secret="sec")


def _client(handler) -> IC2Client:
    c = IC2Client(_creds())
    transport = httpx.MockTransport(handler)
    c._client = lambda: httpx.Client(transport=transport, verify=False)  # noqa: SLF001
    return c


def _ok(data):
    return httpx.Response(200, json={"resp_code": "SUCCESS", "data": data})


def _token(_req):
    return httpx.Response(200, json={"access_token": "t", "expires_in": 9999})


def test_explicit_ids_skip_api_calls():
    calls = {"n": 0}

    def handler(request):
        if request.url.path == "/api/oauth2/token":
            return _token(request)
        calls["n"] += 1
        return _ok([])

    client = _client(handler)
    target = resolve_ic2_target(
        client,
        DeviceIC2Mapping(org_id="1", group_id="2", device_id="3", serial="SN-9"),
    )
    assert target == IC2Target(org_id="1", group_id="2", device_id="3", serial="SN-9")
    assert calls["n"] == 0  # no /rest calls needed


def test_resolve_by_serial_in_default_org():
    def handler(request):
        if request.url.path == "/api/oauth2/token":
            return _token(request)
        if request.url.path == "/rest/o/100/d":
            return _ok(
                [
                    {"id": "dev-a", "sn": "AAAA-1111", "group_id": "g1"},
                    {"id": "dev-b", "sn": "BBBB-2222", "group_id": "g2"},
                ]
            )
        return httpx.Response(404)

    client = _client(handler)
    target = resolve_ic2_target(
        client, DeviceIC2Mapping(serial="BBBB-2222"), default_org_id="100"
    )
    assert target.org_id == "100"
    assert target.group_id == "g2"
    assert target.device_id == "dev-b"


def test_resolve_by_serial_walks_orgs_when_no_default():
    def handler(request):
        path = request.url.path
        if path == "/api/oauth2/token":
            return _token(request)
        if path == "/rest/o":
            return _ok([{"id": "10"}, {"id": "20"}])
        if path == "/rest/o/10/d":
            return _ok([{"id": "x", "serial_number": "NOPE", "group_id": "g"}])
        if path == "/rest/o/20/d":
            return _ok([{"id": "found", "serial_number": "WANT-5", "groupId": "g7"}])
        return httpx.Response(404)

    client = _client(handler)
    target = resolve_ic2_target(client, DeviceIC2Mapping(serial="WANT-5"))
    assert (target.org_id, target.group_id, target.device_id) == ("20", "g7", "found")


def test_unknown_serial_raises():
    def handler(request):
        if request.url.path == "/api/oauth2/token":
            return _token(request)
        if request.url.path == "/rest/o":
            return _ok([{"id": "1"}])
        return _ok([])

    client = _client(handler)
    with pytest.raises(IC2ConfigError, match="not found"):
        resolve_ic2_target(client, DeviceIC2Mapping(serial="GHOST"))


def test_cache_avoids_second_walk():
    calls = {"d": 0}

    def handler(request):
        if request.url.path == "/api/oauth2/token":
            return _token(request)
        if request.url.path == "/rest/o/100/d":
            calls["d"] += 1
            return _ok([{"id": "dev", "sn": "S-1", "group_id": "g"}])
        return httpx.Response(404)

    client = _client(handler)
    cache: dict = {}
    mapping = DeviceIC2Mapping(serial="S-1")
    t1 = resolve_ic2_target(client, mapping, default_org_id="100", cache=cache, cache_key="gateway")
    t2 = resolve_ic2_target(client, mapping, default_org_id="100", cache=cache, cache_key="gateway")
    assert t1 == t2
    assert calls["d"] == 1  # second call served from cache
