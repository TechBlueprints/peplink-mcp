"""InControl 2 group-scoped config writes (InControl-managed surfaces).

Bodies are forwarded verbatim — IC2 documents most write payloads as a ``data``
object (see raw-sources/docs/peplink/incontrol2/write-schemas.md). Callers supply the
object; these helpers only attach the org/group path scope.
"""

from __future__ import annotations

from typing import Any

from peplink_ic2.client import IC2Client

_BASE = "/rest/o/{org}/g/{grp}"


# -- VLANs ----------------------------------------------------------------


def update_vlan_config(client: IC2Client, org: str, grp: str, body: Any) -> Any:
    return client.request("POST", f"/rest/o/{org}/g/{grp}/vlan_config", json_body=body)


def delete_vlan_config(client: IC2Client, org: str, grp: str, vlan_id: str) -> Any:
    return client.request("DELETE", f"/rest/o/{org}/g/{grp}/vlan_config/{vlan_id}")


# -- SSID -----------------------------------------------------------------


def put_ssid_settings(client: IC2Client, org: str, grp: str, body: Any) -> Any:
    return client.request("PUT", f"/rest/o/{org}/g/{grp}/ssid_settings", json_body=body)


def put_ssid_profile(client: IC2Client, org: str, grp: str, ssid_id: str, body: Any) -> Any:
    return client.request(
        "PUT", f"/rest/o/{org}/g/{grp}/ssid_profiles/{ssid_id}", json_body=body
    )


# -- Radio ----------------------------------------------------------------


def put_radio_config(client: IC2Client, org: str, grp: str, body: Any) -> Any:
    return client.request("PUT", f"/rest/o/{org}/g/{grp}/put_radio_config", json_body=body)


# -- Firewall -------------------------------------------------------------


def put_firewall_rule_sets(client: IC2Client, org: str, grp: str, body: Any) -> Any:
    return client.request(
        "PUT", f"/rest/o/{org}/g/{grp}/firewall_rule_sets", json_body=body
    )


# -- MAC ACLs -------------------------------------------------------------


def put_grouped_mac(client: IC2Client, org: str, grp: str, body: Any) -> Any:
    return client.request("PUT", f"/rest/o/{org}/g/{grp}/grouped_mac", json_body=body)
