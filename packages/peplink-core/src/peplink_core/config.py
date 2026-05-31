"""Load and validate fleet configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from peplink_core.exceptions import PeplinkConfigError
from peplink_core.snmp.client import SnmpConfig

DeviceKind = Literal["router", "fusionhub", "switch", "ap"]
ManagementMode = Literal["direct", "gateway"]
AuthTier = Literal["read_only", "config_read", "admin"]
McpKeyTier = Literal["read_only", "admin"]


class ClientCredentialsAuth(BaseModel):
    type: Literal["client_credentials"] = "client_credentials"
    client_id: str
    client_secret: str
    scope: str | None = None


class UserpassAuth(BaseModel):
    type: Literal["userpass"] = "userpass"
    username: str
    password: str


DeviceAuth = ClientCredentialsAuth | UserpassAuth


class DeviceAuthPair(BaseModel):
    read_only: DeviceAuth
    config_read: DeviceAuth | None = None
    admin: DeviceAuth | None = None


class IC2ClientCredentials(BaseModel):
    """OAuth2 credentials for the InControl 2 cloud API (api.ic.peplink.com)."""

    grant_type: Literal["client_credentials", "refresh_token"] = "client_credentials"
    client_id: str
    client_secret: str
    refresh_token: str | None = None


class IC2Config(BaseModel):
    """Fleet-wide InControl 2 settings. Credentials come from secrets.yaml.

    Provide a single ``auth`` (used for both reads and writes — IC2 API clients
    inherit the creating user's permissions), or split into tier-specific
    ``read_only`` / ``admin`` credentials (e.g. a read-only IC2 user's client for
    reads, an admin user's client for writes).
    """

    enabled: bool = False
    base_url: str = "https://api.ic.peplink.com"
    default_org_id: str | None = None
    default_group_id: str | None = None
    verify_tls: bool = True
    auth: IC2ClientCredentials | None = None
    read_only: IC2ClientCredentials | None = None
    admin: IC2ClientCredentials | None = None

    @property
    def has_any_auth(self) -> bool:
        return any((self.auth, self.read_only, self.admin))

    def read_credentials(self) -> IC2ClientCredentials | None:
        """Credential for read calls (RO client preferred; falls back to shared/admin)."""
        return self.read_only or self.auth or self.admin

    def write_credentials(self) -> IC2ClientCredentials | None:
        """Credential for write calls (admin/RW client; a read-only client cannot write)."""
        return self.admin or self.auth


class DeviceIC2Mapping(BaseModel):
    """Map a fleet device to its InControl 2 org/group/device identity.

    Provide ``serial`` for auto-resolution (walk orgs/groups/devices), or all of
    ``org_id``/``group_id``/``device_id`` to pin the IC2 identity explicitly.
    """

    serial: str | None = None
    org_id: str | None = None
    group_id: str | None = None
    device_id: str | None = None

    @model_validator(mode="after")
    def serial_or_ids(self) -> DeviceIC2Mapping:
        explicit = self.org_id and self.group_id and self.device_id
        if not self.serial and not explicit:
            raise ValueError(
                "ic2 mapping requires either 'serial' or all of org_id/group_id/device_id"
            )
        return self


class DeviceDiscoveryConfig(BaseModel):
    """Resolve this device's management IP from a gateway router (read-only mesh APIs)."""

    via: str | None = None
    match: dict[str, str] = Field(min_length=1)


class DeviceConfig(BaseModel):
    host: str | None = None
    port: int = 443
    verify_tls: bool = False
    kind: DeviceKind = "router"
    management: ManagementMode = "direct"
    firmware_hint: str | None = None
    discover: DeviceDiscoveryConfig | None = None
    auth: DeviceAuthPair | None = None
    snmp: SnmpConfig | None = None
    ic2: DeviceIC2Mapping | None = None
    config_authority: Literal["device", "ic2", "auto"] = "auto"
    # Logical equipment grouping (e.g. "main", "branch", "mobile"). Conventionally
    # the InControl 2 group name; gateway-managed devices inherit their gateway's site.
    site: str | None = None

    @model_validator(mode="after")
    def host_or_discover(self) -> DeviceConfig:
        # An IC2-only device (cloud-managed, no LAN reach) needs neither host nor
        # discover — only its ic2 mapping. LAN tools won't work on it; IC2 tools will.
        if not self.host and not self.discover and self.ic2 is None:
            raise ValueError(
                "each device requires host, discover, or ic2 (cloud-only) configuration"
            )
        return self

    @property
    def is_ic2_only(self) -> bool:
        """Cloud-managed device with no LAN access (no host/discover, just an ic2 map)."""
        return self.ic2 is not None and not self.host and self.discover is None

    @property
    def host_resolved(self) -> bool:
        return bool(self.host)

    @property
    def base_url(self) -> str:
        if not self.host:
            raise PeplinkConfigError("device host not resolved yet")
        return f"https://{self.host}:{self.port}"


class McpKeyConfig(BaseModel):
    id: str
    key_ref: str
    tier: McpKeyTier
    description: str | None = None


class DefaultsConfig(BaseModel):
    device_id: str | None = None
    gateway_id: str | None = None


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    tool_mode: Literal["lazy", "eager", "meta_only"] = "lazy"


class LoggingConfig(BaseModel):
    level: str = "info"


class FleetConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    devices: dict[str, DeviceConfig]
    mcp_keys: list[McpKeyConfig] = Field(default_factory=list)
    mcp_key_secrets: dict[str, str] = Field(default_factory=dict)
    incontrol2: IC2Config = Field(default_factory=IC2Config)

    @model_validator(mode="after")
    def validate_devices_non_empty(self) -> FleetConfig:
        if not self.devices:
            raise ValueError("at least one device is required")
        if self.defaults.device_id and self.defaults.device_id not in self.devices:
            raise ValueError(f"defaults.device_id unknown: {self.defaults.device_id}")
        if self.defaults.gateway_id and self.defaults.gateway_id not in self.devices:
            raise ValueError(f"defaults.gateway_id unknown: {self.defaults.gateway_id}")
        return self

    @property
    def admin_tools_enabled(self) -> bool:
        return any(device.auth and device.auth.admin for device in self.devices.values())

    @property
    def ic2_enabled(self) -> bool:
        return self.incontrol2.enabled and self.incontrol2.has_any_auth

    @property
    def access_mode(self) -> Literal["read_only", "full"]:
        return "full" if self.admin_tools_enabled else "read_only"

    def effective_site(self, device_id: str) -> str | None:
        """Device's site, inheriting its discover.via gateway's site when unset."""
        device = self.devices.get(device_id)
        if device is None:
            return None
        if device.site:
            return device.site
        if device.discover and device.discover.via:
            gateway = self.devices.get(device.discover.via)
            if gateway and gateway.site:
                return gateway.site
        return None

    def sites(self) -> dict[str, list[str]]:
        """Map each site to its device ids (gateway-inherited sites included)."""
        grouped: dict[str, list[str]] = {}
        for device_id in self.devices:
            site = self.effective_site(device_id)
            if site:
                grouped.setdefault(site, []).append(device_id)
        return grouped

    def get_device(self, device_id: str | None = None) -> tuple[str, DeviceConfig]:
        did = device_id or self.defaults.device_id
        if not did:
            raise PeplinkConfigError("device_id required (no default configured)")
        if did not in self.devices:
            raise PeplinkConfigError(f"unknown device_id: {did}")
        return did, self.devices[did]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise PeplinkConfigError(f"config file not found: {path}")
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise PeplinkConfigError(f"config root must be a mapping: {path}")
    return data


def _merge_device_auth(base: dict[str, Any], secrets: dict[str, Any]) -> None:
    base_devices = base.setdefault("devices", {})
    secret_devices = secrets.get("devices") or {}
    if not isinstance(secret_devices, dict):
        raise PeplinkConfigError("secrets.devices must be a mapping")

    auth_profiles = secrets.get("auth_profiles") or {}
    if not isinstance(auth_profiles, dict):
        raise PeplinkConfigError("secrets.auth_profiles must be a mapping")

    for device_id, secret_entry in secret_devices.items():
        if not isinstance(secret_entry, dict):
            continue
        auth = secret_entry.get("auth")
        if auth is None:
            profile_name = secret_entry.get("auth_profile")
            if profile_name:
                auth = auth_profiles.get(profile_name)
                if auth is None:
                    raise PeplinkConfigError(
                        f"devices.{device_id}.auth_profile unknown: {profile_name}"
                    )
        device = base_devices.setdefault(device_id, {})
        if not isinstance(device, dict):
            raise PeplinkConfigError(f"devices.{device_id} must be a mapping")
        if auth is not None:
            device["auth"] = auth
        snmp = secret_entry.get("snmp")
        if snmp is not None:
            device["snmp"] = snmp
        ic2 = secret_entry.get("ic2")
        if ic2 is not None:
            device["ic2"] = ic2
        host = secret_entry.get("host")
        if host:
            device["host"] = host


def _merge_ic2(base: dict[str, Any], secrets: dict[str, Any]) -> None:
    """Merge secret InControl 2 credentials into the config's incontrol2 block."""
    secret_ic2 = secrets.get("incontrol2")
    if not isinstance(secret_ic2, dict):
        return
    base_ic2 = base.setdefault("incontrol2", {})
    if not isinstance(base_ic2, dict):
        raise PeplinkConfigError("incontrol2 must be a mapping")
    for key in ("auth", "read_only", "admin"):
        if secret_ic2.get(key) is not None:
            base_ic2[key] = secret_ic2[key]
    for key in ("default_org_id", "default_group_id"):
        if secret_ic2.get(key) is not None:
            base_ic2[key] = secret_ic2[key]


def load_fleet_config(
    config_path: Path | str | None = None,
    secrets_path: Path | str | None = None,
) -> FleetConfig:
    """Load config.yaml and optional secrets.yaml into a validated FleetConfig."""
    cfg_path = Path(
        config_path or os.environ.get("PEPLINK_MCP_CONFIG", "examples/config/config.yaml")
    )
    sec_path = Path(
        secrets_path or os.environ.get("PEPLINK_MCP_SECRETS", "examples/config/secrets.yaml")
    )

    merged = _load_yaml(cfg_path)
    if sec_path.exists():
        secrets = _load_yaml(sec_path)
        _merge_device_auth(merged, secrets)
        _merge_ic2(merged, secrets)
        key_secrets = secrets.get("mcp_keys")
        if isinstance(key_secrets, dict):
            merged["mcp_key_secrets"] = key_secrets
    elif sec_path != Path("/dev/null"):
        # secrets optional for validate-only, required for doctor with auth
        pass

    missing_auth: list[str] = []
    missing_read_only: list[str] = []
    missing_ap_snmp: list[str] = []
    for device_id, device in merged.get("devices", {}).items():
        if not isinstance(device, dict):
            continue
        # IC2-only devices (cloud-managed, no LAN host/discover) need no LAN auth/snmp.
        if device.get("ic2") and not device.get("host") and not device.get("discover"):
            continue
        kind = device.get("kind", "router")
        auth = device.get("auth")
        if kind == "ap":
            if device.get("snmp") is None:
                missing_ap_snmp.append(device_id)
            if auth is None:
                continue
        elif auth is None:
            missing_auth.append(device_id)
            continue
        if not isinstance(auth, dict) or auth.get("read_only") is None:
            missing_read_only.append(device_id)

    if missing_auth:
        raise PeplinkConfigError(
            "devices missing auth in secrets.yaml (use devices.<id>.auth or "
            f"devices.<id>.auth_profile): {', '.join(sorted(missing_auth))}"
        )
    if missing_read_only:
        raise PeplinkConfigError(
            "devices missing read_only auth tier in secrets.yaml: "
            f"{', '.join(sorted(missing_read_only))}"
        )
    if missing_ap_snmp:
        raise PeplinkConfigError(
            "AP devices require devices.<id>.snmp.community in secrets.yaml: "
            f"{', '.join(sorted(missing_ap_snmp))}"
        )

    ic2_block = merged.get("incontrol2")
    if isinstance(ic2_block, dict) and ic2_block.get("enabled"):
        if not any(ic2_block.get(k) for k in ("auth", "read_only", "admin")):
            raise PeplinkConfigError(
                "incontrol2.enabled is true but no credentials found in secrets.yaml — "
                "set incontrol2.auth (single client used for both tiers) or "
                "incontrol2.read_only / incontrol2.admin"
            )

    try:
        return FleetConfig.model_validate(merged)
    except Exception as exc:
        raise PeplinkConfigError(str(exc)) from exc
