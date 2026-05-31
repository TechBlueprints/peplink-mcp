"""`ic2-sync` — propose/apply fleet device → InControl 2 serial + site mappings.

Joins each fleet device to its IC2 record (by explicit serial, else name/model from
discover.match), and reports the IC2 serial + site (= IC2 group name). Default is a
dry run; ``--write`` emits a synced copy of the config so you can review/merge (never
clobbers your commented config, never touches secrets).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from peplink_core.bootstrap import default_secrets_conf_path, load_runtime_fleet
from peplink_core.config import DeviceConfig, FleetConfig, IC2Config
from peplink_core.secrets_ini import load_ic2_secrets
from peplink_ic2 import IC2Client
from peplink_ic2.automap import FleetHint, IC2Index, match_device
from peplink_ic2.endpoints import inventory


def _ic2_for_sync(fleet: FleetConfig) -> IC2Config | None:
    """IC2 config from the fleet, or fall back to a secrets.conf file."""
    if fleet.ic2_enabled:
        return fleet.incontrol2
    path = Path(os.environ.get("PEPLINK_SECRETS_CONF", str(default_secrets_conf_path())))
    if path.exists():
        return load_ic2_secrets(path)
    return None


def _hint(device_id: str, device: DeviceConfig) -> FleetHint:
    serial = device.ic2.serial if device.ic2 else None
    match = device.discover.match if device.discover else {}
    return FleetHint(
        device_id=device_id,
        serial=serial or match.get("serial"),
        mac=match.get("mac"),
        name=match.get("name") or device_id,
        model=match.get("model"),
    )


def _device_list(client: IC2Client, org_id: str) -> list[dict[str, Any]]:
    data = inventory.list_devices(client, org_id)
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    for key in ("devices", "data", "list"):
        inner = data.get(key) if isinstance(data, dict) else None
        if isinstance(inner, list):
            return [r for r in inner if isinstance(r, dict)]
    return []


def run_ic2_sync(
    *,
    config_path: str | None,
    secrets_path: str | None,
    write: bool,
    client: IC2Client | None = None,
) -> int:
    fleet = load_runtime_fleet(config_path, secrets_path)
    ic2 = _ic2_for_sync(fleet)
    if ic2 is None or ic2.read_credentials() is None:
        print(
            "ic2-sync: InControl 2 credentials not found (enable incontrol2 in config/"
            "secrets, or set peplink.ic2*_clientid/secret in secrets.conf)"
        )
        return 1
    org_id = ic2.default_org_id
    if client is None:
        client = IC2Client(
            ic2.read_credentials(), base_url=ic2.base_url, verify_tls=ic2.verify_tls
        )
    if not org_id:
        orgs = client.request("GET", "/rest/o")
        org_id = (orgs[0].get("id") if isinstance(orgs, list) and orgs else None)
        if not org_id:
            print("ic2-sync: no default_org_id and could not infer one from /rest/o")
            return 1

    groups = inventory.summarize_groups(inventory.list_groups(client, org_id)).get("groups", [])
    group_names = {str(g["id"]): g["name"] for g in groups if g.get("id")}
    index = IC2Index.build(_device_list(client, org_id), group_names=group_names)

    proposals: dict[str, dict[str, str | None]] = {}
    print(f"ic2-sync: org {org_id}, {len(index.records)} IC2 devices\n")
    header = f"{'device':24} {'confidence':10} {'site':12} ic2 (serial)"
    print(header)
    print("-" * len(header))
    for device_id in sorted(fleet.devices):
        device = fleet.devices[device_id]
        result = match_device(_hint(device_id, device), index)
        cur_site = fleet.effective_site(device_id)
        if result.record is not None:
            site = index.site_of(result.record) or cur_site
            ic2_name = result.record.get("name")
            line = (
                f"{device_id:24} {result.confidence:10} "
                f"{(site or '-'):12} {ic2_name} ({result.serial})"
            )
            print(line)
            proposals[device_id] = {"serial": result.serial, "site": site}
        elif result.confidence == "ambiguous":
            cands = ", ".join(
                f"{c.get('name')}({c.get('sn')})" for c in result.candidates[:4]
            )
            print(f"{device_id:24} {'AMBIGUOUS':10} {(cur_site or '-'):12} → {cands}")
        else:
            print(f"{device_id:24} {'no-match':10} {(cur_site or '-'):12} —")

    print(f"\nMatched {len(proposals)}/{len(fleet.devices)} devices.")
    if not write:
        print("Dry run. Re-run with --write to emit a synced config copy.")
        return 0

    return _write_synced(config_path, secrets_path, proposals)


def _write_synced(
    config_path: str | None, secrets_path: str | None, proposals: dict[str, dict]
) -> int:
    cfg_path = Path(config_path or os.environ.get("PEPLINK_MCP_CONFIG", ""))
    if not cfg_path or not cfg_path.exists():
        print("ic2-sync --write: needs a YAML --config to sync into (got a secrets.conf fleet)")
        return 1
    raw = yaml.safe_load(cfg_path.read_text()) or {}
    devices = raw.setdefault("devices", {})
    changed = 0
    for device_id, prop in proposals.items():
        dev = devices.get(device_id)
        if not isinstance(dev, dict):
            continue
        if prop.get("serial") and not (dev.get("ic2") or {}).get("serial"):
            dev["ic2"] = {"serial": prop["serial"]}
            changed += 1
        if prop.get("site") and dev.get("site") != prop["site"]:
            dev["site"] = prop["site"]
            changed += 1
    out = cfg_path.with_suffix(".synced.yaml")
    out.write_text(yaml.safe_dump(raw, sort_keys=False))
    print(
        f"\nWrote {out} ({changed} field(s) added/updated). Review and merge into "
        f"{cfg_path.name} — note: YAML round-trip drops comments, so merge by hand."
    )
    return 0
