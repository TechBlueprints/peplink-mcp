"""Match fleet devices to InControl 2 devices by serial / MAC / name.

IC2's device records carry the authoritative join keys: ``sn`` (serial),
``lan_mac`` (+ per-interface MACs), ``name``, ``model``/``product_name`` and
``group_name``. A fleet device supplies whatever it knows (an explicit serial,
a MAC from LAN discovery, or just a name/model from ``discover.match``); this
module returns the best IC2 match with a confidence so the caller can write
exact matches and leave fuzzy/ambiguous ones for a human.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Confidence ordering: exact (serial/mac) is safe to auto-write; fuzzy is not.
EXACT = ("serial", "mac")


def _norm_serial(value: Any) -> str | None:
    if not value:
        return None
    return str(value).strip().upper()


def _norm_mac(value: Any) -> str | None:
    if not value:
        return None
    cleaned = str(value).replace(":", "").replace("-", "").replace(".", "").lower()
    return cleaned or None


def _record_macs(rec: dict[str, Any]) -> list[str]:
    macs = [rec.get("lan_mac"), rec.get("mac")]
    for iface in rec.get("interfaces") or []:
        if isinstance(iface, dict):
            macs.append(iface.get("mac") or iface.get("macAddress"))
    return [m for m in (_norm_mac(x) for x in macs) if m]


def _record_serial(rec: dict[str, Any]) -> str | None:
    return _norm_serial(rec.get("sn") or rec.get("serial_number") or rec.get("serial"))


def _record_model(rec: dict[str, Any]) -> str:
    return str(rec.get("model") or rec.get("product_name") or rec.get("product") or "").lower()


def _record_name(rec: dict[str, Any]) -> str:
    return str(rec.get("name") or "").lower()


@dataclass
class IC2Index:
    records: list[dict[str, Any]]
    by_serial: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_mac: dict[str, dict[str, Any]] = field(default_factory=dict)
    group_names: dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(
        cls, records: list[dict[str, Any]], group_names: dict[str, str] | None = None
    ) -> IC2Index:
        idx = cls(records=records, group_names=group_names or {})
        for rec in records:
            sn = _record_serial(rec)
            if sn:
                idx.by_serial.setdefault(sn, rec)
            for mac in _record_macs(rec):
                idx.by_mac.setdefault(mac, rec)
        return idx

    def site_of(self, rec: dict[str, Any]) -> str | None:
        """Site = IC2 group name (preferring the record's own group_name field)."""
        name = rec.get("group_name")
        if name:
            return str(name)
        gid = rec.get("group_id")
        return self.group_names.get(str(gid)) if gid is not None else None


@dataclass
class FleetHint:
    """What a fleet device knows about itself, for matching."""

    device_id: str
    serial: str | None = None
    mac: str | None = None
    name: str | None = None
    model: str | None = None


@dataclass
class MatchResult:
    device_id: str
    record: dict[str, Any] | None
    confidence: str  # serial | mac | name | model | none | ambiguous
    candidates: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_exact(self) -> bool:
        return self.confidence in EXACT

    @property
    def serial(self) -> str | None:
        return _record_serial(self.record) if self.record else None


def match_device(hint: FleetHint, index: IC2Index) -> MatchResult:
    """Best IC2 match for a fleet device. Exact on serial/MAC, else fuzzy on name/model."""
    sn = _norm_serial(hint.serial)
    if sn and sn in index.by_serial:
        return MatchResult(hint.device_id, index.by_serial[sn], "serial")

    mac = _norm_mac(hint.mac)
    if mac and mac in index.by_mac:
        return MatchResult(hint.device_id, index.by_mac[mac], "mac")

    # Fuzzy: narrow by model, then by name substring.
    pool = index.records
    if hint.model:
        m = hint.model.lower()
        by_model = [r for r in pool if m in _record_model(r) or _record_model(r) in m]
        if by_model:
            pool = by_model
    if hint.name:
        n = hint.name.lower()
        by_name = [r for r in pool if n and n in _record_name(r)]
        if by_name:
            pool = by_name
            confidence = "name"
        elif hint.model and pool is not index.records:
            confidence = "model"
        else:
            confidence = "none"
    elif hint.model and pool is not index.records:
        confidence = "model"
    else:
        confidence = "none"

    if confidence == "none" or not pool:
        return MatchResult(hint.device_id, None, "none")
    if len(pool) == 1:
        return MatchResult(hint.device_id, pool[0], confidence)
    return MatchResult(hint.device_id, None, "ambiguous", candidates=pool)
