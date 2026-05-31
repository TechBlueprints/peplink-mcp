"""Gateway-managed device write routing (Switch Controller, AP Controller)."""

from __future__ import annotations

from peplink_core.config import DeviceConfig, FleetConfig
from peplink_core.exceptions import PeplinkConfigError
from peplink_core.registry import DeviceHandle, DeviceRegistry

ManagementMode = str  # "direct" | "gateway"

# Writes that must go through the gateway when management=gateway.
GATEWAY_WRITE_PATH_PREFIXES = (
    "/api/config.",
    "/api/cmd.",
    "/api/post_config",
)


def is_gateway_managed(device: DeviceConfig) -> bool:
    return device.management == "gateway"


def management_gateway_id(device: DeviceConfig, fleet: FleetConfig) -> str:
    """Return the gateway device_id that owns config writes for this device."""
    if not is_gateway_managed(device):
        raise PeplinkConfigError("management_gateway_id called for a direct-managed device")
    gateway_id = None
    if device.discover and device.discover.via:
        gateway_id = device.discover.via
    gateway_id = gateway_id or fleet.defaults.gateway_id
    if not gateway_id:
        raise PeplinkConfigError(
            "management.gateway requires discover.via or defaults.gateway_id"
        )
    if gateway_id not in fleet.devices:
        raise PeplinkConfigError(f"unknown management gateway: {gateway_id}")
    return gateway_id


def assert_direct_write_allowed(device_id: str, device: DeviceConfig, *, api_path: str) -> None:
    """Block config/cmd writes against a gateway-managed device's direct IP."""
    if not is_gateway_managed(device):
        return
    if not api_path.startswith(GATEWAY_WRITE_PATH_PREFIXES):
        return
    gateway_hint = device.discover.via if device.discover and device.discover.via else "defaults.gateway_id"
    raise PeplinkConfigError(
        f"devices.{device_id} is management=gateway: write {api_path} on the device IP "
        f"is not allowed. Use the gateway ({gateway_hint}) Switch Controller APIs such as "
        "POST /api/config.port with the switch moduleType/moduleId/portId."
    )


def resolve_write_handle(
    registry: DeviceRegistry,
    device_id: str | None,
    *,
    api_path: str,
) -> tuple[DeviceHandle, str | None]:
    """Return the handle to use for a write, and optional proxied_from device_id."""
    _ = api_path
    handle = registry.get(device_id)
    if not is_gateway_managed(handle.config):
        return handle, None
    gateway_id = management_gateway_id(handle.config, registry.fleet)
    if handle.device_id == gateway_id:
        return handle, None
    return registry.get(gateway_id), handle.device_id


def resolve_config_port_read_handle(
    registry: DeviceRegistry,
    device_id: str | None,
) -> tuple[DeviceHandle, str | None]:
    """Pick direct vs gateway client for GET /api/config.port.

    Gateway-managed switches: reads may use the switch IP for detail, but when
    the target is the gateway itself return the gateway handle.
    """
    handle = registry.get(device_id)
    if not is_gateway_managed(handle.config):
        return handle, None
    gateway_id = management_gateway_id(handle.config, registry.fleet)
    if handle.device_id == gateway_id:
        return handle, None
    # Prefer direct switch read when we have a resolved host on the managed device.
    if handle.config.kind == "switch" and handle.config.host:
        return handle, None
    return registry.get(gateway_id), handle.device_id
