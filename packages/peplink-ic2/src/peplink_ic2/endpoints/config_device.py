"""InControl 2 device-scoped writes (WAN priority + destructive ops).

The device-native API proxy (``devapi/{api}``) is intentionally not implemented.
"""

from __future__ import annotations

from typing import Any

from peplink_ic2.client import IC2Client


def _dev(org: str, grp: str, dev: str) -> str:
    return f"/rest/o/{org}/g/{grp}/d/{dev}"


# -- WAN priority (non-destructive config) --------------------------------


def set_wan_priority(client: IC2Client, org: str, grp: str, dev: str, body: Any) -> Any:
    return client.request("POST", f"{_dev(org, grp, dev)}/wan/priority", json_body=body)


# -- Destructive ----------------------------------------------------------


def reboot_device(client: IC2Client, org: str, grp: str, dev: str) -> Any:
    return client.request("POST", f"{_dev(org, grp, dev)}/tools/reboot")


def reset_to_default(client: IC2Client, org: str, grp: str, dev: str) -> Any:
    return client.request("POST", f"{_dev(org, grp, dev)}/tools/reset_default")


def list_config_backups(client: IC2Client, org: str, grp: str, dev: str) -> Any:
    return client.request("GET", f"{_dev(org, grp, dev)}/config_backup")


def restore_config_backup(
    client: IC2Client, org: str, grp: str, dev: str, backup_id: str
) -> Any:
    return client.request(
        "POST", f"{_dev(org, grp, dev)}/config_backup/{backup_id}/restore"
    )
