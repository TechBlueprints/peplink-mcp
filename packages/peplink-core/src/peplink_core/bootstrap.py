"""Runtime bootstrap — resolve fleet config from env or a secrets.conf file."""

from __future__ import annotations

import os
from pathlib import Path

from peplink_core.config import (
    DefaultsConfig,
    DeviceAuthPair,
    DeviceConfig,
    FleetConfig,
    IC2Config,
    load_fleet_config,
)
from peplink_core.exceptions import PeplinkConfigError
from peplink_core.secrets_ini import (
    load_ic2_secrets,
    load_peplink_fusionhub_secrets,
    load_peplink_secrets,
)


def default_secrets_conf_path() -> Path:
    """Default single-device secrets.conf. Override with ``PEPLINK_SECRETS_CONF``."""
    return Path.home() / ".config" / "peplink-mcp" / "secrets.conf"


def fleet_from_secrets_conf(
    *,
    secrets_conf: Path,
    device_id: str = "gateway",
) -> FleetConfig:
    secrets = load_peplink_secrets(secrets_conf)
    pair = DeviceAuthPair(
        read_only=secrets.read_only,
        config_read=secrets.config_read,
        admin=secrets.admin,
    )
    devices: dict[str, DeviceConfig] = {
        device_id: DeviceConfig(
            host=secrets.host,
            verify_tls=False,
            kind="router",
            auth=pair,
        )
    }

    fusionhub = load_peplink_fusionhub_secrets(secrets_conf)
    if fusionhub is not None:
        fh_config_read = fusionhub.config_read
        if fh_config_read is None and fusionhub.admin is not None:
            # FusionHub often has no OAuth clients; admin tier covers config GETs.
            fh_config_read = fusionhub.admin
        devices["fusionhub"] = DeviceConfig(
            host=fusionhub.host,
            verify_tls=False,
            kind="fusionhub",
            auth=DeviceAuthPair(
                read_only=fusionhub.read_only,
                config_read=fh_config_read,
                admin=fusionhub.admin,
            ),
        )

    if device_id not in devices:
        device_id = next(iter(devices))

    incontrol2 = load_ic2_secrets(secrets_conf) or IC2Config()

    return FleetConfig(
        defaults=DefaultsConfig(device_id=device_id),
        devices=devices,
        incontrol2=incontrol2,
    )


def load_runtime_fleet(
    config_path: str | Path | None = None,
    secrets_path: str | Path | None = None,
) -> FleetConfig:
    """Load fleet for MCP server or CLI.

    Priority:
    1. Explicit config + secrets YAML paths (args or PEPLINK_MCP_* env)
    2. PEPLINK_SECRETS_CONF or the default ~/.config/peplink-mcp/secrets.conf
    """
    cfg = config_path or os.environ.get("PEPLINK_MCP_CONFIG")
    sec = secrets_path or os.environ.get("PEPLINK_MCP_SECRETS")

    if cfg and sec:
        return load_fleet_config(cfg, sec)

    if cfg and not sec:
        raise PeplinkConfigError("PEPLINK_MCP_SECRETS required when PEPLINK_MCP_CONFIG is set")

    secrets_conf = Path(
        os.environ.get("PEPLINK_SECRETS_CONF", str(default_secrets_conf_path()))
    )
    if secrets_conf.exists():
        device_id = os.environ.get("PEPLINK_DEVICE_ID", "gateway")
        return fleet_from_secrets_conf(secrets_conf=secrets_conf, device_id=device_id)

    raise PeplinkConfigError(
        "No configuration found. For a multi-device fleet set "
        "PEPLINK_MCP_CONFIG + PEPLINK_MCP_SECRETS (config.yaml + secrets.yaml). "
        "For single-device dev, set PEPLINK_SECRETS_CONF to a secrets.conf file."
    )
