"""Fleet device registry."""

from __future__ import annotations

from dataclasses import dataclass

from peplink_core.client import PeplinkDeviceClient
from peplink_core.config import AuthTier, DeviceConfig, FleetConfig
from peplink_core.exceptions import PeplinkConfigError
from peplink_core.fleet_resolve import resolve_discovered_hosts


@dataclass
class DeviceHandle:
    device_id: str
    config: DeviceConfig
    read_only: PeplinkDeviceClient
    config_read: PeplinkDeviceClient | None
    admin: PeplinkDeviceClient | None

    def client_for_tier(self, tier: AuthTier) -> PeplinkDeviceClient:
        if tier == "read_only":
            return self.read_only
        if tier == "config_read":
            if self.config_read is None:
                raise PeplinkConfigError(
                    f"devices.{self.device_id}: config_read credentials not configured"
                )
            return self.config_read
        if self.admin is None:
            raise PeplinkConfigError(
                f"devices.{self.device_id}: admin credentials not configured "
                "(read-only fleet mode)"
            )
        return self.admin

    def read_client_for_path(self, api_path: str) -> PeplinkDeviceClient:
        """Pick status-read or config-read client for a read-only GET path."""
        needs_config_tier = api_path.startswith("/api/config.") or api_path.startswith("/api/cmd.")
        if needs_config_tier and self.config_read is not None:
            return self.config_read
        return self.read_only


class DeviceRegistry:
    def __init__(self, fleet: FleetConfig) -> None:
        self.fleet = fleet
        self._handles: dict[str, DeviceHandle] = {}
        resolve_discovered_hosts(self.fleet)

    def get(self, device_id: str | None = None) -> DeviceHandle:
        did, device = self.fleet.get_device(device_id)
        if did in self._handles:
            return self._handles[did]
        if device.auth is None or device.auth.read_only is None:
            if device.kind == "ap" and device.snmp is not None:
                raise PeplinkConfigError(
                    f"devices.{did}: HTTP credentials not configured; "
                    "this AP is SNMP-only — use peplink_get_info_firmware, "
                    "peplink_get_config_ssid_profile, peplink_get_status_client, "
                    "peplink_get_status_lan_profile, peplink_get_status_device, "
                    "or peplink_get_status_wlan"
                )
            raise PeplinkConfigError(f"devices.{did}.auth.read_only not configured")
        if not device.host:
            raise PeplinkConfigError(f"devices.{did}.host not resolved")

        config_read_client = None
        if device.auth.config_read is not None:
            config_read_client = PeplinkDeviceClient(
                device.base_url,
                device.auth.config_read,
                "config_read",
                verify_tls=device.verify_tls,
            )

        admin_client = None
        if device.auth.admin is not None:
            admin_client = PeplinkDeviceClient(
                device.base_url,
                device.auth.admin,
                "admin",
                verify_tls=device.verify_tls,
            )

        handle = DeviceHandle(
            device_id=did,
            config=device,
            read_only=PeplinkDeviceClient(
                device.base_url,
                device.auth.read_only,
                "read_only",
                verify_tls=device.verify_tls,
            ),
            config_read=config_read_client,
            admin=admin_client,
        )
        self._handles[did] = handle
        return handle
