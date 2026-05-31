"""Peplink device HTTP client, auth, fleet registry, and API endpoints."""

from peplink_core.bootstrap import load_runtime_fleet
from peplink_core.config import FleetConfig, load_fleet_config
from peplink_core.doctor import DoctorReport, run_doctor
from peplink_core.exceptions import (
    PeplinkAPIError,
    PeplinkAuthError,
    PeplinkConfigError,
    PeplinkConnectionError,
    PeplinkError,
)
from peplink_core.registry import DeviceHandle, DeviceRegistry

__version__ = "0.0.0"

__all__ = [
    "DeviceHandle",
    "DeviceRegistry",
    "DoctorReport",
    "FleetConfig",
    "PeplinkAPIError",
    "PeplinkAuthError",
    "PeplinkConfigError",
    "PeplinkConnectionError",
    "PeplinkError",
    "load_fleet_config",
    "load_runtime_fleet",
    "run_doctor",
]
