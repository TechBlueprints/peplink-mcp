"""End-to-end tests for the bearer-key ASGI middleware."""

from __future__ import annotations

from peplink_mcp_shared.auth_middleware import BearerKeyMiddleware
from peplink_mcp_shared.mcp_keys import McpKeyStore, Principal, _KeyRecord, get_principal
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

RO_SECRET = "00000000-0000-4000-8000-000000000001"
ADMIN_SECRET = "11111111-1111-4111-8111-111111111111"


def _store() -> McpKeyStore:
    return McpKeyStore(
        [
            _KeyRecord(RO_SECRET, Principal("ro", "read_only", source="http-bearer")),
            _KeyRecord(ADMIN_SECRET, Principal("adm", "admin", source="http-bearer")),
        ]
    )


def _client() -> TestClient:
    async def whoami(_request: Request) -> JSONResponse:
        p = get_principal()
        return JSONResponse(
            {"key_id": p.key_id if p else None, "tier": p.tier if p else None}
        )

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    app = Starlette(
        routes=[Route("/mcp", whoami), Route("/health", health)],
    )
    app.add_middleware(BearerKeyMiddleware, store=_store())
    return TestClient(app)


def test_missing_key_rejected():
    resp = _client().get("/mcp")
    assert resp.status_code == 401
    assert "missing" in resp.json()["detail"]
    assert resp.headers["www-authenticate"].startswith("Bearer")


def test_invalid_key_rejected():
    resp = _client().get("/mcp", headers={"Authorization": "Bearer wrong-key-totally-invalid"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid MCP key"


def test_read_only_key_binds_principal():
    resp = _client().get("/mcp", headers={"Authorization": f"Bearer {RO_SECRET}"})
    assert resp.status_code == 200
    assert resp.json() == {"key_id": "ro", "tier": "read_only"}


def test_admin_key_binds_principal():
    resp = _client().get("/mcp", headers={"Authorization": f"Bearer {ADMIN_SECRET}"})
    assert resp.status_code == 200
    assert resp.json() == {"key_id": "adm", "tier": "admin"}


def test_health_bypasses_auth():
    resp = _client().get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_principal_not_leaked_after_request():
    client = _client()
    client.get("/mcp", headers={"Authorization": f"Bearer {ADMIN_SECRET}"})
    # A subsequent unauthenticated call must not see the prior principal.
    resp = client.get("/mcp")
    assert resp.status_code == 401


def test_non_bearer_scheme_rejected():
    resp = _client().get("/mcp", headers={"Authorization": f"Basic {RO_SECRET}"})
    assert resp.status_code == 401
