"""Policy gates for destructive operations.

Authentication (a valid MCP key) and authorization (admin tier) say *who* may
call a tool. Policy gates are an orthogonal third leg: even an admin caller may
only invoke a dangerous family (reboot, WAN disable, SMS send, config apply,
auth-client mutation) when the operator has explicitly enabled it via a
``PEPLINK_POLICY_ALLOW_*`` environment flag. The gate defaults to **deny**.

This matches the risk-register guarantee of a triple gate:
read-only-key-denied + explicit confirm + policy flag.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_TRUTHY = {"1", "true", "yes", "on"}
_POLICY_PREFIX = "PEPLINK_POLICY_ALLOW_"


class PolicyError(Exception):
    """A tool's policy flag is not enabled in the environment."""


class ConfirmationRequired(Exception):
    """A destructive tool was called without an explicit ``confirm=true``."""

    def __init__(self, tool: str, action: str) -> None:
        super().__init__(
            f"{tool} is destructive ({action}). Re-call with confirm=true to proceed."
        )


@dataclass(frozen=True)
class PolicyGate:
    """Snapshot of which ``PEPLINK_POLICY_ALLOW_*`` flags are enabled."""

    allowed: frozenset[str]

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "PolicyGate":
        env = environ if environ is not None else dict(os.environ)
        allowed = {
            name
            for name, value in env.items()
            if name.startswith(_POLICY_PREFIX) and value.strip().lower() in _TRUTHY
        }
        return cls(frozenset(allowed))

    def allows(self, policy_key: str | None) -> bool:
        """True if a tool with ``policy_key`` may run. Ungated tools always pass."""
        if not policy_key:
            return True
        return policy_key in self.allowed

    def require(self, policy_key: str | None, *, tool: str) -> None:
        """Raise PolicyError if ``policy_key`` is set but not enabled."""
        if self.allows(policy_key):
            return
        raise PolicyError(
            f"{tool} is gated by {policy_key}, which is not enabled. Set "
            f"{policy_key}=1 in the server environment to allow this operation."
        )
