"""Discover managed Peplink devices via a gateway router (read-only GETs)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from peplink_core.client import PeplinkDeviceClient
from peplink_core.endpoints.status import (
    get_clients,
    get_extap_mesh,
    get_extap_mesh_link,
    get_wan_connection,
)
from peplink_core.exceptions import PeplinkConfigError


@dataclass(frozen=True)
class DiscoveredPeer:
    name: str | None
    host: str
    mac: str | None = None
    model: str | None = None
    mesh_id: str | None = None
    kind_hint: str | None = None
    source: str = "gateway"


def _norm_mac(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"[^a-f0-9]", "", value.lower())


def _peer_from_mapping(data: dict[str, Any], *, source: str, mesh_id: str | None = None) -> DiscoveredPeer | None:
    host = data.get("ip") or data.get("host") or data.get("managementIp")
    if not host:
        return None
    return DiscoveredPeer(
        name=data.get("name") or data.get("hostname"),
        host=str(host),
        mac=data.get("mac"),
        model=data.get("model") or data.get("product"),
        mesh_id=mesh_id or data.get("meshId"),
        kind_hint=data.get("type") or data.get("deviceType"),
        source=source,
    )


def parse_discovered_peers(mesh: dict[str, Any], mesh_link: dict[str, Any]) -> list[DiscoveredPeer]:
    """Extract peer devices from gateway mesh status payloads."""
    peers: list[DiscoveredPeer] = []
    seen_hosts: set[str] = set()

    def add(peer: DiscoveredPeer | None) -> None:
        if peer is None or peer.host in seen_hosts:
            return
        seen_hosts.add(peer.host)
        peers.append(peer)

    order = mesh.get("order") or []
    if isinstance(order, list):
        for entry_id in order:
            entry = mesh.get(str(entry_id), {})
            if not isinstance(entry, dict):
                continue
            mesh_id = entry.get("meshId")
            raw_peers = entry.get("peer") or entry.get("peers") or []
            if isinstance(raw_peers, list):
                for item in raw_peers:
                    if isinstance(item, dict):
                        add(_peer_from_mapping(item, source="status.extap.mesh", mesh_id=mesh_id))
            elif isinstance(raw_peers, dict):
                for item in raw_peers.values():
                    if isinstance(item, dict):
                        add(_peer_from_mapping(item, source="status.extap.mesh", mesh_id=mesh_id))

    nodes = mesh_link.get("nodes") or {}
    if isinstance(nodes, dict):
        for node in nodes.values():
            if isinstance(node, dict):
                add(_peer_from_mapping(node, source="status.extap.mesh.link"))

    return peers


_SYNERGY_CONNECTED_RE = re.compile(r"Connected to (\S+) \(Synergy\)", re.I)


def parse_synergy_peers(wan: dict[str, Any], *, gateway_host: str) -> list[DiscoveredPeer]:
    """Extract synergized router serials from controller WAN status.

    Resolved host is always ``gateway_host`` — synergized devices have no direct LAN REST.
    """
    peers: list[DiscoveredPeer] = []
    seen_serials: set[str] = set()

    for key, entry in wan.items():
        if key == "order" or not isinstance(entry, dict):
            continue
        serial: str | None = None
        if entry.get("synergyLink"):
            match = _SYNERGY_CONNECTED_RE.search(str(entry.get("message") or ""))
            if match:
                serial = match.group(1)
        elif entry.get("synergy"):
            name = str(entry.get("name") or "")
            if " - " in name:
                serial = name.rsplit(" - ", 1)[-1].strip()

        if not serial or serial in seen_serials:
            continue
        seen_serials.add(serial)
        peers.append(
            DiscoveredPeer(
                name=serial,
                host=gateway_host,
                kind_hint="synergized_router",
                source="status.wan.connection",
            )
        )

    return peers


def parse_lan_clients(data: dict[str, Any]) -> list[DiscoveredPeer]:
    """Extract LAN clients from gateway status.client (APs show as clientType 18)."""
    items = data.get("list") or data.get("client") or []
    if not isinstance(items, list):
        return []

    peers: list[DiscoveredPeer] = []
    seen_hosts: set[str] = set()
    for entry in items:
        if not isinstance(entry, dict):
            continue
        host = entry.get("ip")
        if not host or host in seen_hosts:
            continue
        seen_hosts.add(str(host))
        peers.append(
            DiscoveredPeer(
                name=entry.get("name"),
                host=str(host),
                mac=entry.get("mac"),
                model=entry.get("clientType"),
                kind_hint="ap" if str(entry.get("clientType")) == "18" else None,
                source="status.client",
            )
        )
    return peers


def discover_lan_clients(gateway_client: PeplinkDeviceClient) -> list[DiscoveredPeer]:
    return parse_lan_clients(get_clients(gateway_client, active_only=False))


def discover_mesh_peers(gateway_client: PeplinkDeviceClient) -> list[DiscoveredPeer]:
    mesh = get_extap_mesh(gateway_client)
    mesh_link = get_extap_mesh_link(gateway_client)
    return parse_discovered_peers(mesh, mesh_link)


def discover_synergy_peers(
    gateway_client: PeplinkDeviceClient,
    *,
    gateway_host: str,
) -> list[DiscoveredPeer]:
    wan = get_wan_connection(gateway_client)
    return parse_synergy_peers(wan, gateway_host=gateway_host)


def match_discovered_peer(
    peers: list[DiscoveredPeer],
    match: dict[str, str],
    *,
    device_id: str,
) -> DiscoveredPeer:
    if not match:
        raise PeplinkConfigError(f"devices.{device_id}.discover.match must not be empty")

    candidates = peers
    for key, expected in match.items():
        expected_norm = expected.strip().lower()
        next_candidates: list[DiscoveredPeer] = []
        for peer in candidates:
            if key in ("name", "hostname"):
                name = (peer.name or "").lower()
                if expected_norm in name or name == expected_norm:
                    next_candidates.append(peer)
            elif key == "mac":
                if _norm_mac(peer.mac) == _norm_mac(expected):
                    next_candidates.append(peer)
            elif key in ("mesh_id", "meshId"):
                if (peer.mesh_id or "").lower() == expected_norm:
                    next_candidates.append(peer)
            elif key in ("host", "ip"):
                if peer.host == expected:
                    next_candidates.append(peer)
            elif key in ("model", "product"):
                model = (peer.model or "").lower()
                if expected_norm in model or model == expected_norm:
                    next_candidates.append(peer)
            elif key in ("client_type", "clientType"):
                ctype = str(peer.model or "").lower()
                if ctype == expected_norm:
                    next_candidates.append(peer)
            elif key == "serial":
                serial = (peer.name or "").lower()
                if serial == expected_norm or expected_norm in serial:
                    next_candidates.append(peer)
            else:
                raise PeplinkConfigError(
                    f"devices.{device_id}.discover.match unsupported key: {key}"
                )
        candidates = next_candidates

    if not candidates:
        available = [
            {
                "name": p.name,
                "host": p.host,
                "mac": p.mac,
                "model": p.model,
                "mesh_id": p.mesh_id,
            }
            for p in peers
        ]
        raise PeplinkConfigError(
            f"devices.{device_id}: no gateway peer matched {match}. "
            f"Discovered: {available or '(none)'}"
        )
    if len(candidates) > 1:
        raise PeplinkConfigError(
            f"devices.{device_id}: discover.match matched multiple peers: "
            f"{[c.host for c in candidates]}"
        )
    return candidates[0]
