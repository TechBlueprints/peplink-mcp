"""Config-write authority precedence with break-glass override.

When a device can be configured through more than one control plane, peplink-mcp
prefers the **highest** one that is configured and capable, but lets an operator
"break the glass" and drop to a lower plane on purpose.

Precedence (highest → lowest):

1. **ic2** — InControl 2 cloud, when IC2 is enabled, the device has an `ic2:` mapping,
   the device's `config_authority` isn't pinned to `device`, and the requested config
   path has an InControl-managed equivalent (`IC2_MANAGED_PATHS`).
2. **gateway** — the controller (Switch/AP Controller) when the device is
   `management: gateway` and the path is a gateway-routed write.
3. **device** — the device's own LAN API.

A device write tool consults `plan_write_authority`:

- If the preferred plane is **ic2** and the caller did not override, it raises
  `ConfigAuthorityRedirect` pointing at the `peplink_ic2_*` tool — the agent should
  use IC2, or pass `override="gateway"`/`override="device"` to break the glass.
- If the preferred plane is **gateway**, the write routes to the gateway by default;
  `override="device"` forces a direct-to-device write when the device supports it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from peplink_core.config import DeviceConfig
from peplink_core.management import GATEWAY_WRITE_PATH_PREFIXES, is_gateway_managed

Authority = Literal["ic2", "gateway", "device"]

# Device LAN API path -> the InControl-managed equivalent tool. Extend as IC2
# config coverage grows. Keep keys as exact device API paths.
IC2_MANAGED_PATHS: dict[str, str] = {
    "/api/config.ssid.profile": "peplink_ic2_put_ssid_settings",
    "/api/config.wan.connection.priority": "peplink_ic2_set_wan_priority",
    "/api/config.lan": "peplink_ic2_set_vlan_config",
    "/api/cmd.system.reboot": "peplink_ic2_reboot_device",
}


class ConfigAuthorityRedirect(Exception):
    """A write should go through a higher control plane (e.g. InControl 2)."""

    def __init__(self, path: str, preferred: Authority, ic2_tool: str | None) -> None:
        self.path = path
        self.preferred = preferred
        self.ic2_tool = ic2_tool
        hint = f"use {ic2_tool}" if ic2_tool else f"use the {preferred} plane"
        super().__init__(
            f"{path} is managed by InControl 2 for this device — {hint}, or pass "
            "override='gateway' (controller) or override='device' (direct LAN, break-glass) "
            "to write here anyway."
        )


def ic2_equivalent_tool(path: str) -> str | None:
    return IC2_MANAGED_PATHS.get(path)


def preferred_authority(device: DeviceConfig, path: str, *, ic2_enabled: bool) -> Authority:
    """The highest configured + capable plane for writing ``path`` on ``device``."""
    ic2_tool = ic2_equivalent_tool(path)
    if (
        ic2_enabled
        and device.ic2 is not None
        and ic2_tool is not None
        and device.config_authority != "device"
    ):
        return "ic2"
    if is_gateway_managed(device) and path.startswith(GATEWAY_WRITE_PATH_PREFIXES):
        return "gateway"
    return "device"


@dataclass(frozen=True)
class WritePlan:
    """How a device write should be routed after applying precedence + override."""

    level: Authority  # the plane the write will actually use
    preferred: Authority  # the plane precedence would have chosen
    overridden: bool  # True when the caller broke the glass to a lower plane


def plan_write_authority(
    device: DeviceConfig,
    path: str,
    *,
    ic2_enabled: bool,
    override: str | None,
) -> WritePlan:
    """Decide which plane a device write uses; raise to redirect to InControl 2.

    ``override`` (caller break-glass): ``None`` (respect precedence), ``"gateway"``,
    or ``"device"``. Raises ``ConfigAuthorityRedirect`` if IC2 is preferred and no
    override was given. Raises ``ValueError`` for an override that escalates rather
    than de-escalates.
    """
    if override not in (None, "", "gateway", "device"):
        raise ValueError(f"override must be 'gateway' or 'device', got {override!r}")
    override = override or None

    preferred = preferred_authority(device, path, ic2_enabled=ic2_enabled)

    if preferred == "ic2":
        if override is None:
            raise ConfigAuthorityRedirect(path, "ic2", ic2_equivalent_tool(path))
        # break glass down to gateway or device
        return WritePlan(level=override, preferred="ic2", overridden=True)

    if preferred == "gateway":
        if override == "device":
            return WritePlan(level="device", preferred="gateway", overridden=True)
        # override="gateway" is a no-op at this level; precedence already chose gateway
        return WritePlan(level="gateway", preferred="gateway", overridden=False)

    # preferred == "device": nothing higher to override away from
    return WritePlan(level="device", preferred="device", overridden=False)
