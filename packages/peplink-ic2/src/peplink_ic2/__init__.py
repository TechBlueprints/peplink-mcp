"""InControl 2 (Peplink cloud) OAuth2 client, resolver, and endpoint layer."""

from peplink_ic2.client import IC2Client
from peplink_ic2.config import DeviceIC2Mapping, IC2ClientCredentials, IC2Config
from peplink_ic2.doctor import IC2DoctorReport, run_ic2_doctor
from peplink_ic2.exceptions import (
    IC2APIError,
    IC2AuthError,
    IC2ConfigError,
    IC2ConnectionError,
    IC2Error,
    IC2RateLimitError,
)
from peplink_ic2.resolver import IC2Target, resolve_ic2_target

__version__ = "0.0.0"

__all__ = [
    "DeviceIC2Mapping",
    "IC2APIError",
    "IC2AuthError",
    "IC2Client",
    "IC2ClientCredentials",
    "IC2Config",
    "IC2ConfigError",
    "IC2ConnectionError",
    "IC2DoctorReport",
    "IC2Error",
    "IC2RateLimitError",
    "IC2Target",
    "resolve_ic2_target",
    "run_ic2_doctor",
]
