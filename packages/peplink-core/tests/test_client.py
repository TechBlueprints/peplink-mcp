"""HTTP client tests with mocked transport."""

from __future__ import annotations

import httpx
import pytest
from peplink_core.client import PeplinkDeviceClient
from peplink_core.config import ClientCredentialsAuth
from peplink_core.exceptions import PeplinkAPIError


def _grant_response(token: str = "tok-abc") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "stat": "ok",
            "response": {"accessToken": token, "expiresIn": "3600"},
        },
    )


def _wan_lite_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "stat": "ok",
            "response": {"order": [1, 2], "1": {"name": "WAN1", "enable": True}},
        },
    )


def test_client_credentials_grant_and_ping():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/api/auth.token.grant":
            return _grant_response()
        if request.url.path == "/api/status.wan.connection":
            assert "accessToken=tok-abc" in str(request.url)
            return _wan_lite_response()
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="https://router.test") as _:
        client = PeplinkDeviceClient(
            "https://router.test",
            ClientCredentialsAuth(client_id="id", client_secret="secret"),
            "read_only",
            verify_tls=False,
        )
        client._client = lambda: httpx.Client(  # noqa: SLF001
            transport=transport,
            base_url="https://router.test",
            verify=False,
        )
        result = client.ping()
        assert result["order"] == [1, 2]
        assert any("auth.token.grant" in c for c in calls)


def test_api_fail_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth.token.grant":
            return _grant_response()
        return httpx.Response(
            200,
            json={"stat": "fail", "code": 3, "message": "invalid connId"},
        )

    transport = httpx.MockTransport(handler)
    client = PeplinkDeviceClient(
        "https://router.test",
        ClientCredentialsAuth(client_id="id", client_secret="secret"),
        "admin",
        verify_tls=False,
    )
    client._client = lambda: httpx.Client(transport=transport, base_url="https://router.test", verify=False)  # noqa: SLF001

    with pytest.raises(PeplinkAPIError) as exc:
        client.request("GET", "/api/cmd.sms.get", query={"connId": 99})
    assert exc.value.code == 3


def test_grant_failure_raises_auth_error():
    transport = httpx.MockTransport(
        lambda _req: httpx.Response(
            200,
            json={"stat": "fail", "message": "bad secret"},
        )
    )
    client = PeplinkDeviceClient(
        "https://router.test",
        ClientCredentialsAuth(client_id="id", client_secret="bad"),
        "read_only",
        verify_tls=False,
    )
    client._client = lambda: httpx.Client(transport=transport, base_url="https://router.test", verify=False)  # noqa: SLF001

    with pytest.raises(PeplinkAPIError):
        client.ensure_authenticated()


def test_grant_retries_transient_internal_error():
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/api/auth.token.grant":
            return httpx.Response(404)
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(
                200,
                json={"stat": "fail", "code": 401, "message": "Internal Error"},
            )
        return _grant_response("tok-retry")

    transport = httpx.MockTransport(handler)
    client = PeplinkDeviceClient(
        "https://router.test",
        ClientCredentialsAuth(client_id="id", client_secret="secret"),
        "read_only",
        verify_tls=False,
    )
    client._client = lambda: httpx.Client(transport=transport, base_url="https://router.test", verify=False)  # noqa: SLF001

    client.ensure_authenticated()
    assert attempts["count"] == 2


def test_request_retries_transient_internal_error():
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth.token.grant":
            return _grant_response()
        if request.url.path == "/api/status.wan.connection":
            attempts["count"] += 1
            if attempts["count"] == 1:
                return httpx.Response(
                    200,
                    json={"stat": "fail", "message": "Internal Error"},
                )
            return _wan_lite_response()
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = PeplinkDeviceClient(
        "https://router.test",
        ClientCredentialsAuth(client_id="id", client_secret="secret"),
        "read_only",
        verify_tls=False,
    )
    client._client = lambda: httpx.Client(transport=transport, base_url="https://router.test", verify=False)  # noqa: SLF001

    result = client.ping()
    assert result["order"] == [1, 2]
    assert attempts["count"] == 2
