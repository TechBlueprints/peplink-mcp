"""Map a fleet device to its InControl 2 org/group/device identity.

Explicit ids in config win. Otherwise we resolve by serial number: list the devices
in the candidate org(s) (``GET /rest/o/{org}/d``) and match on the device serial.
Results are cached per fleet ``device_id`` for the process lifetime since IC2
identities rarely change and the org→device walk costs API calls (rate-limited).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from peplink_core.config import DeviceIC2Mapping

from peplink_ic2.client import IC2Client
from peplink_ic2.exceptions import IC2ConfigError

# Keys IC2 device records may use for the serial and the org/group/device ids.
_SERIAL_KEYS = ("sn", "serial_number", "serialNumber", "serial")
_DEVICE_ID_KEYS = ("id", "device_id", "deviceId")
_GROUP_ID_KEYS = ("group_id", "groupId", "gid", "group")
_ORG_ID_KEYS = ("org_id", "orgId", "oid", "organization_id")


@dataclass(frozen=True)
class IC2Target:
    org_id: str
    group_id: str
    device_id: str
    serial: str | None = None


def _first(record: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, dict):  # e.g. group: {"id": ...}
            value = value.get("id")
        if value not in (None, ""):
            return str(value)
    return None


def _iter_records(data: Any) -> list[dict[str, Any]]:
    """IC2 list payloads are usually a list; tolerate {'devices': [...]} too."""
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("devices", "data", "list"):
            inner = data.get(key)
            if isinstance(inner, list):
                return [r for r in inner if isinstance(r, dict)]
    return []


def _match_in_org(client: IC2Client, org_id: str, serial: str) -> IC2Target | None:
    data = client.request("GET", f"/rest/o/{org_id}/d")
    target_serial = serial.strip().lower()
    for record in _iter_records(data):
        rec_serial = _first(record, _SERIAL_KEYS)
        if rec_serial and rec_serial.strip().lower() == target_serial:
            device_id = _first(record, _DEVICE_ID_KEYS)
            group_id = _first(record, _GROUP_ID_KEYS)
            if device_id and group_id:
                return IC2Target(
                    org_id=_first(record, _ORG_ID_KEYS) or org_id,
                    group_id=group_id,
                    device_id=device_id,
                    serial=rec_serial,
                )
    return None


def resolve_ic2_target(
    client: IC2Client,
    mapping: DeviceIC2Mapping,
    *,
    default_org_id: str | None = None,
    cache: dict[str, IC2Target] | None = None,
    cache_key: str | None = None,
) -> IC2Target:
    """Resolve a ``DeviceIC2Mapping`` to a concrete ``IC2Target``.

    Raises ``IC2ConfigError`` if a serial cannot be located in any accessible org.
    """
    if cache is not None and cache_key is not None and cache_key in cache:
        return cache[cache_key]

    # Explicit ids pin the identity — no API call needed.
    if mapping.org_id and mapping.group_id and mapping.device_id:
        target = IC2Target(
            org_id=mapping.org_id,
            group_id=mapping.group_id,
            device_id=mapping.device_id,
            serial=mapping.serial,
        )
    elif mapping.serial:
        target = _resolve_by_serial(client, mapping.serial, default_org_id)
    else:  # pragma: no cover - guarded by DeviceIC2Mapping validator
        raise IC2ConfigError("ic2 mapping has neither explicit ids nor a serial")

    if cache is not None and cache_key is not None:
        cache[cache_key] = target
    return target


def _resolve_by_serial(client: IC2Client, serial: str, default_org_id: str | None) -> IC2Target:
    # Try the hinted org first to avoid a full walk.
    if default_org_id:
        found = _match_in_org(client, default_org_id, serial)
        if found:
            return found

    orgs = _iter_records(client.request("GET", "/rest/o"))
    for org in orgs:
        org_id = _first(org, _ORG_ID_KEYS) or _first(org, _DEVICE_ID_KEYS)
        if not org_id or org_id == default_org_id:
            continue
        found = _match_in_org(client, org_id, serial)
        if found:
            return found

    raise IC2ConfigError(
        f"InControl 2 device with serial {serial!r} not found in any accessible organization"
    )
