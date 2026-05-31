"""Audit logging for privileged MCP tool calls.

Every admin-tier / write invocation is recorded so there is a trail of which MCP
key acted on which device. Records go to the dedicated ``peplink.audit`` logger
(INFO for allowed actions, WARNING for gate denials) so operators can route or
retain them independently of normal server logs.
"""

from __future__ import annotations

import logging

from peplink_mcp_shared.mcp_keys import Principal

audit_logger = logging.getLogger("peplink.audit")


def _who(principal: Principal | None) -> str:
    if principal is None:
        return "key=<none> tier=<none>"
    return f"key={principal.key_id} tier={principal.tier}"


def record_action(
    principal: Principal | None,
    *,
    tool: str,
    method: str,
    path: str,
    device_id: str,
    decision: str,
    detail: str | None = None,
) -> None:
    """Log one privileged tool invocation.

    ``decision`` is "allow" (action sent to the device) or "deny:<reason>"
    (blocked by a tier/policy/confirm gate before reaching the device).
    """
    msg = (
        f"audit {_who(principal)} tool={tool} {method} {path} "
        f"device={device_id} decision={decision}"
    )
    if detail:
        msg += f" detail={detail}"
    if decision.startswith("deny"):
        audit_logger.warning(msg)
    else:
        audit_logger.info(msg)
