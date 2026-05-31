"""Application context shared by MCP tools."""

from __future__ import annotations

from dataclasses import dataclass, field

from peplink_core.config import DeviceConfig, FleetConfig, McpKeyTier
from peplink_core.exceptions import PeplinkConfigError
from peplink_core.fleet_resolve import resolve_discovered_hosts
from peplink_core.fleet_summary import fleet_capabilities, fleet_device_summaries
from peplink_core.registry import DeviceHandle, DeviceRegistry

from peplink_mcp_shared.mcp_keys import McpKeyStore, Principal, get_principal, require_tier
from peplink_mcp_shared.policy import PolicyGate


@dataclass
class AppContext:
    fleet: FleetConfig
    registry: DeviceRegistry
    key_store: McpKeyStore = field(default_factory=lambda: McpKeyStore([]))
    policy: PolicyGate = field(default_factory=lambda: PolicyGate(frozenset()))

    def current_principal(self) -> Principal | None:
        """The MCP caller bound to the current request (None when unauthenticated)."""
        return get_principal()

    def require_tier(self, required: McpKeyTier) -> Principal:
        """Authorize the current caller for a ``required``-tier tool."""
        return require_tier(required)

    def require_policy(self, policy_key: str | None, *, tool: str) -> None:
        """Enforce a destructive-op policy flag (no-op when unset)."""
        self.policy.require(policy_key, tool=tool)

    def resolve_device(self, device_id: str | None) -> DeviceHandle:
        return self.registry.get(device_id)

    def resolve_ap_snmp(self, device_id: str | None) -> tuple[str, DeviceConfig]:
        """Return (device_id, DeviceConfig) for AP SNMP tools."""
        resolve_discovered_hosts(self.fleet)
        did, device = self.fleet.get_device(device_id)
        if device.kind != "ap":
            raise PeplinkConfigError(
                f"devices.{did} is kind={device.kind}; SNMP AP tools require kind=ap"
            )
        if device.snmp is None:
            raise PeplinkConfigError(f"devices.{did}.snmp not configured in secrets.yaml")
        if not device.host:
            raise PeplinkConfigError(f"devices.{did}.host not resolved")
        return did, device

    def list_devices(self) -> list[dict]:
        return fleet_device_summaries(self.fleet)

    def capabilities(self) -> dict:
        return fleet_capabilities(self.fleet)
