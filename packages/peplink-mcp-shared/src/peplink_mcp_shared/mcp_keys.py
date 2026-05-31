"""MCP API-key authentication: principals, key store, and tier gating.

This is the *caller-facing* auth layer. It is independent of the per-device
Peplink credential tiers in ``peplink_core``: an MCP key authenticates the agent
connecting to this server and binds it to an ``McpKeyTier`` (``read_only`` or
``admin``), which gates which tools that caller may invoke. The server then uses
the appropriate per-device credential pool to actually talk to the hardware.

Keys are plaintext GUIDs supplied in ``secrets.yaml`` (``mcp_keys`` mapping) and
referenced from ``config.yaml`` (``mcp_keys[].key_ref``). Verification is a
constant-time compare so a valid-length guess cannot be timed against the store.
"""

from __future__ import annotations

import hmac
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from peplink_core.config import FleetConfig, McpKeyConfig, McpKeyTier
from peplink_core.exceptions import PeplinkConfigError

# Higher rank == more privilege. A principal may call any tool whose required
# tier rank is <= the principal's rank.
_TIER_RANK: dict[McpKeyTier, int] = {"read_only": 0, "admin": 1}

# Prefix used in config.yaml key_ref values (e.g. "mcp_keys.cursor_readonly").
_KEY_REF_PREFIX = "mcp_keys."


class McpAuthError(Exception):
    """Caller failed authentication (no/invalid MCP key)."""


class McpAuthzError(Exception):
    """Caller is authenticated but lacks the tier required for a tool."""


@dataclass(frozen=True)
class Principal:
    """An authenticated MCP caller."""

    key_id: str
    tier: McpKeyTier
    source: str = "unknown"
    description: str | None = None

    def allows(self, required: McpKeyTier) -> bool:
        return tier_allows(self.tier, required)


def tier_allows(principal_tier: McpKeyTier, required: McpKeyTier) -> bool:
    """True if a caller at ``principal_tier`` may call a ``required``-tier tool."""
    return _TIER_RANK[principal_tier] >= _TIER_RANK[required]


def resolve_key_ref(key_ref: str) -> str:
    """Map a config ``key_ref`` to its lookup name in the secrets mapping."""
    if key_ref.startswith(_KEY_REF_PREFIX):
        return key_ref[len(_KEY_REF_PREFIX) :]
    return key_ref


@dataclass(frozen=True)
class _KeyRecord:
    secret: str
    principal: Principal


class McpKeyStore:
    """Resolved set of MCP keys, with constant-time verification."""

    def __init__(self, records: list[_KeyRecord]) -> None:
        self._records = records

    @classmethod
    def from_fleet(cls, fleet: FleetConfig) -> "McpKeyStore":
        records: list[_KeyRecord] = []
        seen_ids: set[str] = set()
        seen_secrets: dict[str, str] = {}
        for key in fleet.mcp_keys:
            if key.id in seen_ids:
                raise PeplinkConfigError(f"duplicate mcp_keys id: {key.id}")
            seen_ids.add(key.id)

            secret = cls._lookup_secret(fleet, key)
            if secret in seen_secrets:
                raise PeplinkConfigError(
                    f"mcp_keys '{key.id}' and '{seen_secrets[secret]}' share the same secret"
                )
            seen_secrets[secret] = key.id

            records.append(
                _KeyRecord(
                    secret=secret,
                    principal=Principal(
                        key_id=key.id,
                        tier=key.tier,
                        source="http-bearer",
                        description=key.description,
                    ),
                )
            )
        return cls(records)

    @staticmethod
    def _lookup_secret(fleet: FleetConfig, key: McpKeyConfig) -> str:
        name = resolve_key_ref(key.key_ref)
        secret = fleet.mcp_key_secrets.get(name)
        if not secret:
            raise PeplinkConfigError(
                f"mcp_keys '{key.id}' key_ref '{key.key_ref}' has no secret in "
                f"secrets.yaml mcp_keys.{name}"
            )
        if not isinstance(secret, str) or len(secret.strip()) < 16:
            raise PeplinkConfigError(
                f"mcp_keys '{key.id}' secret is too short; use a GUID/long random token"
            )
        return secret.strip()

    @property
    def configured(self) -> bool:
        return bool(self._records)

    @property
    def key_count(self) -> int:
        return len(self._records)

    def tiers(self) -> set[McpKeyTier]:
        return {r.principal.tier for r in self._records}

    def verify(self, token: str | None) -> Principal | None:
        """Return the matching Principal for ``token``, or None.

        Constant-time across all records so a caller cannot probe which prefix
        of a key is correct by timing. Returns None for an empty token.
        """
        if not token:
            return None
        match: Principal | None = None
        # Compare against every record so total time does not depend on which
        # (if any) matched. hmac.compare_digest is itself length-safe.
        for record in self._records:
            if hmac.compare_digest(record.secret, token):
                match = record.principal
        return match


# --- current-principal binding (transport-agnostic) ------------------------

_current_principal: ContextVar[Principal | None] = ContextVar(
    "peplink_current_principal", default=None
)


def get_principal() -> Principal | None:
    """The principal bound to the current request/session, if any."""
    return _current_principal.get()


def set_principal(principal: Principal | None) -> None:
    """Bind a principal for the current context (e.g. stdio startup)."""
    _current_principal.set(principal)


@contextmanager
def bind_principal(principal: Principal | None) -> Iterator[None]:
    """Bind ``principal`` for the duration of the block, then restore."""
    token = _current_principal.set(principal)
    try:
        yield
    finally:
        _current_principal.reset(token)


def require_tier(required: McpKeyTier) -> Principal:
    """Assert the current caller may use a ``required``-tier tool.

    Returns the authenticated Principal. Raises ``McpAuthError`` if no principal
    is bound (unauthenticated) and ``McpAuthzError`` if the principal's tier is
    insufficient.
    """
    principal = get_principal()
    if principal is None:
        raise McpAuthError("no authenticated MCP key bound to this request")
    if not principal.allows(required):
        raise McpAuthzError(
            f"MCP key '{principal.key_id}' (tier={principal.tier}) is not permitted "
            f"to call {required}-tier tools"
        )
    return principal
