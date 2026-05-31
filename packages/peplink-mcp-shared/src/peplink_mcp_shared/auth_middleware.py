"""ASGI bearer-key middleware for the streamable-HTTP MCP transport.

Authenticates every HTTP request against an :class:`McpKeyStore` using the
``Authorization: Bearer <guid>`` header, binds the resolved :class:`Principal`
into the request context (so tools can read it via ``get_principal()``), and
rejects unknown/missing keys with ``401``.

Paths in ``public_paths`` (default: ``/health``) bypass auth so liveness checks
work without a key. This middleware is for the *network* transport only; stdio
binds its principal at startup from the environment.

Requires ``stateless_http=True`` on the FastMCP server so each request is handled
inline in the request task — that is what makes the per-request ContextVar
binding visible to the tool call.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from peplink_mcp_shared.mcp_keys import McpKeyStore, bind_principal

Scope = dict
Receive = Callable[[], Awaitable[dict]]
Send = Callable[[dict], Awaitable[None]]

_DEFAULT_PUBLIC_PATHS = ("/health",)


class BearerKeyMiddleware:
    """Pure-ASGI middleware enforcing MCP bearer keys on HTTP requests."""

    def __init__(
        self,
        app: Callable,
        store: McpKeyStore,
        *,
        public_paths: tuple[str, ...] = _DEFAULT_PUBLIC_PATHS,
    ) -> None:
        self.app = app
        self.store = store
        self.public_paths = public_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if any(path == p or path.startswith(p + "/") for p in self.public_paths):
            await self.app(scope, receive, send)
            return

        token = _bearer_token(scope)
        principal = self.store.verify(token)
        if principal is None:
            await _send_401(send, present=token is not None)
            return

        with bind_principal(principal):
            await self.app(scope, receive, send)


def _bearer_token(scope: Scope) -> str | None:
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name == b"authorization":
            value = raw_value.decode("latin-1").strip()
            if value.lower().startswith("bearer "):
                return value[7:].strip()
            return None
    return None


async def _send_401(send: Send, *, present: bool) -> None:
    detail = "invalid MCP key" if present else "missing Authorization: Bearer <key>"
    body = json.dumps({"error": "unauthorized", "detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b'Bearer realm="peplink-mcp"'),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
