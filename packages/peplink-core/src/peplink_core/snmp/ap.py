"""Peplink AP One status via Pepwave enterprise MIB (1.3.6.1.4.1.27662)."""

from __future__ import annotations

import re
from typing import Any

from peplink_core.snmp.client import SnmpConfig, SnmpSession, SnmpVarbind

PEPWAVE_ENTERPRISE = "1.3.6.1.4.1.27662.200.1.1"

# apSystem scalars (27662.200.1.1.1.*)
AP_SERIAL = f"{PEPWAVE_ENTERPRISE}.1.1.1.1.0"
AP_MAC = f"{PEPWAVE_ENTERPRISE}.1.1.1.2.0"
AP_FIRMWARE = f"{PEPWAVE_ENTERPRISE}.1.1.1.3.0"
AP_UPTIME = f"{PEPWAVE_ENTERPRISE}.1.1.1.5.0"
AP_WAN_STATUS = f"{PEPWAVE_ENTERPRISE}.1.1.1.7.0"
AP_GATEWAY = f"{PEPWAVE_ENTERPRISE}.1.1.1.8.0"
AP_HOSTNAME = f"{PEPWAVE_ENTERPRISE}.1.2.1.1.0"
AP_LOCATION = f"{PEPWAVE_ENTERPRISE}.1.2.1.2.0"
AP_LAN_IP = f"{PEPWAVE_ENTERPRISE}.2.1.1.2.0"
AP_LAN_MASK = f"{PEPWAVE_ENTERPRISE}.2.1.1.3.0"
AP_LAN_GATEWAY = f"{PEPWAVE_ENTERPRISE}.2.1.1.4.0"
AP_LAN_DNS = f"{PEPWAVE_ENTERPRISE}.2.1.1.5.0"

# ap-wlan-mib current SSID + counters
AP_CURRENT_SSID = f"{PEPWAVE_ENTERPRISE}.4.1.1.1.2.0"
AP_CURRENT_BSSID = f"{PEPWAVE_ENTERPRISE}.4.1.1.1.3.0"
AP_WLAN_RX_BYTES = f"{PEPWAVE_ENTERPRISE}.4.1.2.1.1.0"
AP_WLAN_TX_BYTES = f"{PEPWAVE_ENTERPRISE}.4.1.2.1.2.0"
AP_WLAN_RX_PACKETS = f"{PEPWAVE_ENTERPRISE}.4.1.2.1.3.0"
AP_WLAN_TX_PACKETS = f"{PEPWAVE_ENTERPRISE}.4.1.2.1.4.0"

# apRadio — first radio channel (5 GHz index .1.1.1.4.1 on dual-radio units)
AP_RADIO0_CHANNEL = f"{PEPWAVE_ENTERPRISE}.3.1.1.1.4.1"
AP_RADIO1_CHANNEL = f"{PEPWAVE_ENTERPRISE}.3.1.1.1.4.0"

# ap-wlan-mib config tables (read-only GET parity with /api/config.ssid.profile)
AP_WLAN_SSID_PROFILE_TABLE = f"{PEPWAVE_ENTERPRISE}.4.2.1.1"
AP_WLAN_SSID_ADVANCED_TABLE = f"{PEPWAVE_ENTERPRISE}.4.2.2.1"
AP_WLAN_NETWORK_TABLE = f"{PEPWAVE_ENTERPRISE}.2.1.1"

SSID_PROFILE_COLUMN_ID = "1"
SSID_PROFILE_COLUMN_SSID = "4"
SSID_PROFILE_COLUMN_ENABLE = "5"
SSID_PROFILE_COLUMN_SECURITY = "13"

SSID_ADVANCED_COLUMN_VLAN = "2"
SSID_ADVANCED_COLUMN_BAND = "7"
SSID_ADVANCED_COLUMN_PASSPHRASE = "10"

SECURITY_TYPE_LABELS = {
    0: "open",
    1: "wep",
    2: "wpa_personal",
    3: "wpa2_personal",
    4: "wpa2_enterprise",
    5: "wpa3_personal",
}

SENSITIVE_SNMP_COLUMNS = {SSID_ADVANCED_COLUMN_PASSPHRASE}

# Wireless client table (indexed rows under .6.1.1.1.<column>.<...>)
AP_CLIENT_TABLE = f"{PEPWAVE_ENTERPRISE}.6.1.1.1"

CLIENT_COLUMN_MAC = "2"
CLIENT_COLUMN_IP = "3"
CLIENT_COLUMN_NAME = "4"
CLIENT_COLUMN_DURATION = "5"
CLIENT_COLUMN_JOINED = "6"
CLIENT_COLUMN_SIGNAL = "7"
CLIENT_COLUMN_TX_BYTES = "8"
CLIENT_COLUMN_RX_BYTES = "9"
CLIENT_COLUMN_BAND = "10"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _counter(value: Any) -> int | None:
    parsed = _int(value)
    if parsed is None and value is not None:
        try:
            return int(str(value))
        except ValueError:
            return None
    return parsed


def normalize_mac(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "asOctets"):
        raw_bytes = bytes(value.asOctets())
        if len(raw_bytes) == 6:
            return ":".join(f"{b:02X}" for b in raw_bytes)
    raw = str(value).strip()
    if raw.startswith("0x"):
        raw = raw[2:]
    raw = re.sub(r"[^0-9a-fA-F]", "", raw)
    if len(raw) < 12:
        return None
    raw = raw[:12]
    return ":".join(raw[i : i + 2].upper() for i in range(0, 12, 2))


def _redact_if_sensitive(column: str, value: Any) -> Any:
    if column in SENSITIVE_SNMP_COLUMNS:
        text = _text(value)
        if text and not set(text) <= {"*"}:
            return "[redacted]"
        return text or "[redacted]"
    return value


def _parse_indexed_table(
    rows: list[SnmpVarbind],
    base_oid: str,
    *,
    index_filter: str | None = r"^\d+$",
) -> dict[str, dict[str, Any]]:
    """Group SNMP walk rows into table entries keyed by index suffix."""
    prefix = base_oid.rstrip(".") + "."
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not row.oid.startswith(prefix):
            continue
        suffix = row.oid[len(prefix) :]
        parts = suffix.split(".")
        if len(parts) < 2:
            continue
        column, *index_parts = parts
        index = ".".join(index_parts)
        if index_filter and not re.fullmatch(index_filter, index):
            continue
        grouped.setdefault(index, {"index": index})[column] = row.value
    return grouped


def parse_ssid_profile_table(rows: list[SnmpVarbind], base_oid: str) -> dict[str, dict[str, Any]]:
    """Parse ap-wlan-mib SSID profile table (4.2.1.1)."""
    raw = _parse_indexed_table(rows, base_oid)
    grouped: dict[str, dict[str, Any]] = {}
    for index, columns in raw.items():
        entry: dict[str, Any] = {"index": index}
        if SSID_PROFILE_COLUMN_ID in columns:
            entry["profile_id"] = _int(columns[SSID_PROFILE_COLUMN_ID])
        if SSID_PROFILE_COLUMN_SSID in columns:
            entry["ssid"] = _text(columns[SSID_PROFILE_COLUMN_SSID])
        if SSID_PROFILE_COLUMN_ENABLE in columns:
            entry["enable"] = bool(_int(columns[SSID_PROFILE_COLUMN_ENABLE]))
        if SSID_PROFILE_COLUMN_SECURITY in columns:
            code = _int(columns[SSID_PROFILE_COLUMN_SECURITY])
            entry["security_type"] = code
            entry["security"] = SECURITY_TYPE_LABELS.get(code, f"unknown_{code}")
        grouped[index] = entry
    return grouped


def parse_ssid_advanced_table(rows: list[SnmpVarbind], base_oid: str) -> dict[str, dict[str, Any]]:
    """Parse ap-wlan-mib SSID advanced table (4.2.2.1)."""
    raw = _parse_indexed_table(rows, base_oid)
    grouped: dict[str, dict[str, Any]] = {}
    for index, columns in raw.items():
        entry: dict[str, Any] = {"index": index}
        if SSID_ADVANCED_COLUMN_VLAN in columns:
            entry["vlan_id"] = _int(columns[SSID_ADVANCED_COLUMN_VLAN])
        if SSID_ADVANCED_COLUMN_BAND in columns:
            entry["band"] = _int(columns[SSID_ADVANCED_COLUMN_BAND])
        if SSID_ADVANCED_COLUMN_PASSPHRASE in columns:
            entry["passphrase"] = _redact_if_sensitive(
                SSID_ADVANCED_COLUMN_PASSPHRASE,
                columns[SSID_ADVANCED_COLUMN_PASSPHRASE],
            )
        grouped[index] = entry
    return grouped


def parse_snmp_table(rows: list[SnmpVarbind], base_oid: str) -> dict[str, dict[str, Any]]:
    """Backward-compatible alias for SSID profile table parsing in tests."""
    return parse_ssid_profile_table(rows, base_oid)


def fetch_ap_ssid_profile_config(host: str, snmp: SnmpConfig) -> dict[str, Any]:
    """REST-shaped payload analogous to GET /api/config.ssid.profile."""
    config_snmp = SnmpConfig(
        community=snmp.config_read_community,
        config_community=snmp.config_community,
        port=snmp.port,
        timeout_sec=snmp.timeout_sec,
        retries=snmp.retries,
    )
    session = SnmpSession(host, config_snmp)
    profiles = parse_ssid_profile_table(
        session.walk(AP_WLAN_SSID_PROFILE_TABLE),
        AP_WLAN_SSID_PROFILE_TABLE,
    )
    advanced = parse_ssid_advanced_table(
        session.walk(AP_WLAN_SSID_ADVANCED_TABLE),
        AP_WLAN_SSID_ADVANCED_TABLE,
    )

    order: list[int] = []
    response: dict[str, Any] = {}
    for index, profile in sorted(profiles.items(), key=lambda item: int(item[0])):
        ssid = profile.get("ssid")
        if not ssid:
            continue
        adv = advanced.get(index, {})
        profile_id = profile.get("profile_id")
        if profile_id is None:
            try:
                profile_id = int(index)
            except ValueError:
                profile_id = len(order)
        pid = int(profile_id)
        order.append(pid)
        response[str(pid)] = {
            "name": ssid,
            "enable": profile.get("enable"),
            "ssid": ssid,
            "security": profile.get("security"),
            "security_type": profile.get("security_type"),
            "vlan_id": adv.get("vlan_id"),
            "band": adv.get("band"),
            "passphrase": adv.get("passphrase"),
        }
    return {"order": order, **response}


def ap_device_status_as_info_firmware(status: dict[str, Any]) -> dict[str, Any]:
    firmware = status.get("firmware")
    if not firmware:
        return {}
    return {"1": {"version": firmware, "inUse": True}}


def fetch_ap_lan_profile(host: str, snmp: SnmpConfig) -> dict[str, Any]:
    """REST-shaped payload analogous to GET /api/status.lan.profile."""
    session = SnmpSession(host, snmp)
    values = session.get_many([AP_LAN_IP, AP_LAN_MASK, AP_LAN_GATEWAY, AP_LAN_DNS])
    return {
        "order": [0],
        "0": {
            "name": "LAN",
            "ip": _text(values.get(AP_LAN_IP)),
            "mask": _int(values.get(AP_LAN_MASK)),
            "gateway": _text(values.get(AP_LAN_GATEWAY)),
            "dns": _text(values.get(AP_LAN_DNS)),
        },
    }


def probe_ap_snmp_read(host: str, snmp: SnmpConfig) -> tuple[bool, str]:
    """Lightweight status-tier SNMP probe."""
    try:
        status = fetch_ap_device_status(host, snmp)
        if not status.get("firmware"):
            return False, "SNMP reachable but apSystem OIDs returned no firmware"
        return True, f"SNMP ok; firmware {status['firmware']}"
    except Exception as exc:
        return False, str(exc)


def probe_ap_snmp_config_read(host: str, snmp: SnmpConfig) -> tuple[bool, str]:
    """Lightweight config-read-tier SNMP probe."""
    try:
        data = fetch_ap_ssid_profile_config(host, snmp)
        count = len(data.get("order", []))
        if count == 0:
            return False, "SNMP config walk ok but no SSID profiles found"
        return True, f"SNMP config ok; {count} SSID profile(s)"
    except Exception as exc:
        return False, str(exc)


def parse_client_table(rows: list[SnmpVarbind]) -> list[dict[str, Any]]:
    """Group apClientTable walk rows into client records."""
    prefix = AP_CLIENT_TABLE + "."
    grouped: dict[str, dict[str, Any]] = {}

    for row in rows:
        if not row.oid.startswith(prefix):
            continue
        suffix = row.oid[len(prefix) :]
        parts = suffix.split(".")
        if len(parts) < 2:
            continue
        column, *index_parts = parts
        index = ".".join(index_parts)
        entry = grouped.setdefault(index, {"index": index})

        if column == CLIENT_COLUMN_MAC:
            entry["mac"] = normalize_mac(row.value)
        elif column == CLIENT_COLUMN_IP:
            if type(row.value).__name__ == "IpAddress":
                octets = getattr(row.value, "asOctets", lambda: None)()
                entry["ip"] = (
                    ".".join(str(b) for b in octets) if octets and len(octets) == 4 else _text(row.value)
                )
            else:
                entry["ip"] = _text(row.value)
        elif column == CLIENT_COLUMN_NAME:
            name = _text(row.value)
            if name and name != "UNKNOWN":
                entry["name"] = name
        elif column == CLIENT_COLUMN_DURATION:
            entry["duration"] = _text(row.value)
        elif column == CLIENT_COLUMN_JOINED:
            entry["joined_at"] = _text(row.value)
        elif column == CLIENT_COLUMN_SIGNAL:
            entry["signal"] = _int(row.value)
        elif column == CLIENT_COLUMN_TX_BYTES:
            entry["tx_bytes"] = _counter(row.value)
        elif column == CLIENT_COLUMN_RX_BYTES:
            entry["rx_bytes"] = _counter(row.value)
        elif column == CLIENT_COLUMN_BAND:
            entry["band"] = _int(row.value)

    clients = [c for c in grouped.values() if c.get("mac") or c.get("ip")]
    clients.sort(key=lambda c: (c.get("ip") or "", c.get("mac") or ""))
    return clients


def fetch_ap_device_status(host: str, snmp: SnmpConfig) -> dict[str, Any]:
    session = SnmpSession(host, snmp)
    values = session.get_many(
        [
            AP_SERIAL,
            AP_MAC,
            AP_FIRMWARE,
            AP_UPTIME,
            AP_WAN_STATUS,
            AP_GATEWAY,
            AP_HOSTNAME,
            AP_LOCATION,
            AP_LAN_IP,
        ]
    )
    return {
        "serial_number": _text(values.get(AP_SERIAL)),
        "mac": normalize_mac(values.get(AP_MAC)),
        "firmware": _text(values.get(AP_FIRMWARE)),
        "uptime_ticks": _int(values.get(AP_UPTIME)),
        "wan_status": _text(values.get(AP_WAN_STATUS)),
        "gateway": _text(values.get(AP_GATEWAY)),
        "hostname": _text(values.get(AP_HOSTNAME)),
        "location": _text(values.get(AP_LOCATION)),
        "lan_ip": _text(values.get(AP_LAN_IP)),
    }


def fetch_ap_wlan_summary(host: str, snmp: SnmpConfig) -> dict[str, Any]:
    session = SnmpSession(host, snmp)
    values = session.get_many(
        [
            AP_CURRENT_SSID,
            AP_CURRENT_BSSID,
            AP_WLAN_RX_BYTES,
            AP_WLAN_TX_BYTES,
            AP_WLAN_RX_PACKETS,
            AP_WLAN_TX_PACKETS,
            AP_RADIO0_CHANNEL,
            AP_RADIO1_CHANNEL,
        ]
    )
    bssids = _text(values.get(AP_CURRENT_BSSID))
    return {
        "ssid": _text(values.get(AP_CURRENT_SSID)),
        "bssids": bssids.split() if bssids else [],
        "rx_bytes": _counter(values.get(AP_WLAN_RX_BYTES)),
        "tx_bytes": _counter(values.get(AP_WLAN_TX_BYTES)),
        "rx_packets": _counter(values.get(AP_WLAN_RX_PACKETS)),
        "tx_packets": _counter(values.get(AP_WLAN_TX_PACKETS)),
        "radio_channels": {
            "radio0": _int(values.get(AP_RADIO1_CHANNEL)),
            "radio1": _int(values.get(AP_RADIO0_CHANNEL)),
        },
    }


def fetch_ap_wlan_clients(host: str, snmp: SnmpConfig) -> dict[str, Any]:
    session = SnmpSession(host, snmp)
    rows = session.walk(AP_CLIENT_TABLE)
    clients = parse_client_table(rows)
    return {
        "client_count": len(clients),
        "clients": clients,
    }
