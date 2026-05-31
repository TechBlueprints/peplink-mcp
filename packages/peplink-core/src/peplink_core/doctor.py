"""Connectivity and auth diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from peplink_core.config import DeviceConfig, FleetConfig, load_fleet_config
from peplink_core.exceptions import PeplinkConfigError, PeplinkError
from peplink_core.fleet_resolve import resolve_discovered_hosts
from peplink_core.registry import DeviceRegistry
from peplink_core.snmp.ap import probe_ap_snmp_config_read, probe_ap_snmp_read

DoctorTier = Literal["read_only", "config_read", "admin"]


@dataclass
class TierCheckResult:
    tier: DoctorTier
    ok: bool
    auth_type: str
    message: str
    detail: dict | None = None


@dataclass
class DoctorReport:
    device_id: str
    host: str
    kind: str
    base_url: str
    tiers: list[TierCheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(t.ok for t in self.tiers)


def _probe_tier(handle, tier: DoctorTier) -> TierCheckResult:
    client = handle.client_for_tier(tier)
    auth_type = client.auth.type
    try:
        client.ensure_authenticated()
        if tier == "config_read":
            client.request("GET", "/api/config.wan.connection")
            message = "authenticated; config.wan.connection GET ok"
            detail = None
        else:
            ping = client.ping()
            wan_count = len(ping.get("order", [])) if isinstance(ping, dict) else 0
            message = f"authenticated; WAN lite probe ok ({wan_count} WAN slot(s))"
            detail = {"wan_order": ping.get("order")} if isinstance(ping, dict) else None
        return TierCheckResult(
            tier=tier,
            ok=True,
            auth_type=auth_type,
            message=message,
            detail=detail,
        )
    except PeplinkError as exc:
        return TierCheckResult(
            tier=tier,
            ok=False,
            auth_type=auth_type,
            message=str(exc),
        )


def _doctor_ap(device_id: str, device: DeviceConfig) -> DoctorReport:
    if device.snmp is None:
        raise PeplinkConfigError(f"devices.{device_id}.snmp not configured")
    if not device.host:
        raise PeplinkConfigError(f"devices.{device_id}.host not resolved")

    report = DoctorReport(
        device_id=device_id,
        host=device.host,
        kind=device.kind,
        base_url=f"snmp://{device.host}:{device.snmp.port}",
    )

    ok, message = probe_ap_snmp_read(device.host, device.snmp)
    report.tiers.append(
        TierCheckResult(
            tier="read_only",
            ok=ok,
            auth_type="snmp",
            message=message,
        )
    )

    ok, message = probe_ap_snmp_config_read(device.host, device.snmp)
    report.tiers.append(
        TierCheckResult(
            tier="config_read",
            ok=ok,
            auth_type="snmp",
            message=message,
        )
    )

    return report


def run_doctor(
    device_id: str,
    *,
    config_path: str | None = None,
    secrets_path: str | None = None,
    fleet: FleetConfig | None = None,
) -> DoctorReport:
    fleet = fleet or load_fleet_config(config_path, secrets_path)
    resolve_discovered_hosts(fleet)
    _, device = fleet.get_device(device_id)

    if device.kind == "ap":
        return _doctor_ap(device_id, device)

    registry = DeviceRegistry(fleet)
    handle = registry.get(device_id)
    device = handle.config

    report = DoctorReport(
        device_id=handle.device_id,
        host=device.host or "",
        kind=device.kind,
        base_url=device.base_url if device.host else "",
    )

    tiers: list[DoctorTier] = ["read_only"]
    if device.auth and device.auth.config_read is not None:
        tiers.append("config_read")
    if device.auth and device.auth.admin is not None:
        tiers.append("admin")

    for tier in tiers:
        report.tiers.append(_probe_tier(handle, tier))

    return report
