"""Tests for the MCP API-key store and tier gating."""

from __future__ import annotations

import pytest
from peplink_core.config import FleetConfig
from peplink_core.exceptions import PeplinkConfigError
from peplink_mcp_shared.mcp_keys import (
    McpAuthError,
    McpAuthzError,
    McpKeyStore,
    Principal,
    bind_principal,
    get_principal,
    require_tier,
    tier_allows,
)

RO_SECRET = "00000000-0000-4000-8000-000000000001"
ADMIN_SECRET = "11111111-1111-4111-8111-111111111111"


def _fleet(mcp_keys: list[dict], secrets: dict[str, str]) -> FleetConfig:
    return FleetConfig.model_validate(
        {
            "devices": {
                "gateway": {
                    "host": "192.0.2.1",
                    "auth": {
                        "read_only": {
                            "type": "client_credentials",
                            "client_id": "x",
                            "client_secret": "y",
                        }
                    },
                }
            },
            "mcp_keys": mcp_keys,
            "mcp_key_secrets": secrets,
        }
    )


def _two_key_store() -> McpKeyStore:
    fleet = _fleet(
        mcp_keys=[
            {"id": "ro", "key_ref": "mcp_keys.ro", "tier": "read_only"},
            {"id": "adm", "key_ref": "mcp_keys.adm", "tier": "admin"},
        ],
        secrets={"ro": RO_SECRET, "adm": ADMIN_SECRET},
    )
    return McpKeyStore.from_fleet(fleet)


def test_tier_allows_ranking():
    assert tier_allows("admin", "read_only")
    assert tier_allows("admin", "admin")
    assert tier_allows("read_only", "read_only")
    assert not tier_allows("read_only", "admin")


def test_verify_resolves_tier():
    store = _two_key_store()
    assert store.key_count == 2
    assert store.tiers() == {"read_only", "admin"}

    ro = store.verify(RO_SECRET)
    assert ro is not None and ro.key_id == "ro" and ro.tier == "read_only"

    adm = store.verify(ADMIN_SECRET)
    assert adm is not None and adm.key_id == "adm" and adm.tier == "admin"


def test_verify_rejects_unknown_and_empty():
    store = _two_key_store()
    assert store.verify("nope-not-a-real-key-1234") is None
    assert store.verify("") is None
    assert store.verify(None) is None


def test_empty_store_not_configured():
    store = McpKeyStore([])
    assert not store.configured
    assert store.verify(RO_SECRET) is None


def test_missing_secret_raises():
    fleet = _fleet(
        mcp_keys=[{"id": "ro", "key_ref": "mcp_keys.ro", "tier": "read_only"}],
        secrets={},
    )
    with pytest.raises(PeplinkConfigError, match="no secret"):
        McpKeyStore.from_fleet(fleet)


def test_short_secret_raises():
    fleet = _fleet(
        mcp_keys=[{"id": "ro", "key_ref": "mcp_keys.ro", "tier": "read_only"}],
        secrets={"ro": "tooshort"},
    )
    with pytest.raises(PeplinkConfigError, match="too short"):
        McpKeyStore.from_fleet(fleet)


def test_duplicate_id_raises():
    fleet = _fleet(
        mcp_keys=[
            {"id": "dup", "key_ref": "mcp_keys.a", "tier": "read_only"},
            {"id": "dup", "key_ref": "mcp_keys.b", "tier": "admin"},
        ],
        secrets={"a": RO_SECRET, "b": ADMIN_SECRET},
    )
    with pytest.raises(PeplinkConfigError, match="duplicate mcp_keys id"):
        McpKeyStore.from_fleet(fleet)


def test_shared_secret_raises():
    fleet = _fleet(
        mcp_keys=[
            {"id": "a", "key_ref": "mcp_keys.a", "tier": "read_only"},
            {"id": "b", "key_ref": "mcp_keys.b", "tier": "admin"},
        ],
        secrets={"a": RO_SECRET, "b": RO_SECRET},
    )
    with pytest.raises(PeplinkConfigError, match="share the same secret"):
        McpKeyStore.from_fleet(fleet)


def test_require_tier_unauthenticated_raises():
    with bind_principal(None):
        with pytest.raises(McpAuthError):
            require_tier("read_only")


def test_require_tier_read_only_denied_admin():
    ro = Principal("ro", "read_only", source="test")
    with bind_principal(ro):
        assert require_tier("read_only").key_id == "ro"
        with pytest.raises(McpAuthzError):
            require_tier("admin")


def test_require_tier_admin_allows_all():
    adm = Principal("adm", "admin", source="test")
    with bind_principal(adm):
        assert require_tier("read_only").tier == "admin"
        assert require_tier("admin").tier == "admin"


def test_bind_principal_restores():
    assert get_principal() is None
    with bind_principal(Principal("a", "admin")):
        assert get_principal().key_id == "a"
    assert get_principal() is None
