"""IC2Client tests with mocked transport."""

from __future__ import annotations

import httpx
import pytest
from peplink_core.config import IC2ClientCredentials
from peplink_ic2.client import IC2Client
from peplink_ic2.exceptions import IC2APIError, IC2AuthError, IC2RateLimitError


def _creds(**kw) -> IC2ClientCredentials:
    return IC2ClientCredentials(client_id="cid", client_secret="csecret", **kw)


def _bind(client: IC2Client, transport: httpx.MockTransport) -> None:
    client._client = lambda: httpx.Client(transport=transport, verify=False)  # noqa: SLF001


def _token_response(token: str = "tok-1", refresh: str | None = "ref-1") -> httpx.Response:
    body: dict = {"access_token": token, "token_type": "Bearer", "expires_in": 172799}
    if refresh:
        body["refresh_token"] = refresh
    return httpx.Response(200, json=body)


def _ok(data) -> httpx.Response:
    return httpx.Response(200, json={"resp_code": "SUCCESS", "message": "", "data": data})


def test_token_grant_is_form_encoded_and_bearer_is_sent():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/oauth2/token":
            seen["ct"] = request.headers.get("Content-Type")
            seen["body"] = request.content.decode()
            return _token_response()
        if request.url.path == "/rest/o":
            seen["auth"] = request.headers.get("Authorization")
            return _ok([{"id": "1", "name": "Org"}])
        return httpx.Response(404)

    client = IC2Client(_creds())
    _bind(client, httpx.MockTransport(handler))

    data = client.ping()
    assert data == [{"id": "1", "name": "Org"}]
    assert seen["ct"] == "application/x-www-form-urlencoded"
    assert "grant_type=client_credentials" in seen["body"]
    assert "client_id=cid" in seen["body"]
    assert seen["auth"] == "Bearer tok-1"


def test_envelope_failure_raises_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/oauth2/token":
            return _token_response()
        return httpx.Response(200, json={"resp_code": "AUTH_FAILED", "message": "nope"})

    client = IC2Client(_creds())
    _bind(client, httpx.MockTransport(handler))

    with pytest.raises(IC2APIError) as exc:
        client.request("GET", "/rest/o/1/g")
    assert exc.value.resp_code == "AUTH_FAILED"


def test_rate_limit_retries_then_succeeds():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/oauth2/token":
            return _token_response()
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})
        return _ok({"ok": True})

    client = IC2Client(_creds())
    _bind(client, httpx.MockTransport(handler))

    assert client.request("GET", "/rest/o") == {"ok": True}
    assert attempts["n"] == 2


def test_rate_limit_exhausts_and_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/oauth2/token":
            return _token_response()
        return httpx.Response(429, headers={"Retry-After": "0"}, json={})

    client = IC2Client(_creds())
    _bind(client, httpx.MockTransport(handler))

    with pytest.raises(IC2RateLimitError):
        client.request("GET", "/rest/o")


def test_401_triggers_regrant_then_retry():
    state = {"tokens": 0, "data_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/oauth2/token":
            state["tokens"] += 1
            return _token_response(token=f"tok-{state['tokens']}", refresh=None)
        state["data_calls"] += 1
        if state["data_calls"] == 1:
            return httpx.Response(401, json={})
        return _ok([])

    client = IC2Client(_creds())
    _bind(client, httpx.MockTransport(handler))

    assert client.request("GET", "/rest/o") == []
    assert state["tokens"] == 2  # initial grant + re-grant after 401
    assert state["data_calls"] == 2


def test_refresh_token_used_before_client_credentials():
    grants: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/oauth2/token":
            grants.append(request.content.decode())
            return _token_response()
        return _ok("pong")

    client = IC2Client(_creds(refresh_token="seed-refresh"))
    _bind(client, httpx.MockTransport(handler))

    client.ping()
    assert "grant_type=refresh_token" in grants[0]
    assert "refresh_token=seed-refresh" in grants[0]


def test_bad_token_grant_raises_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_client"})

    client = IC2Client(_creds())
    _bind(client, httpx.MockTransport(handler))

    with pytest.raises(IC2AuthError):
        client.ensure_authenticated()
