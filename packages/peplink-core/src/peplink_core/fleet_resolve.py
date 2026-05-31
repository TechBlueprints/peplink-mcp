"""Resolve discovered device hosts via a configured gateway."""

from __future__ import annotations

from peplink_core.client import PeplinkDeviceClient
from peplink_core.config import DeviceConfig, FleetConfig
from peplink_core.discovery import (
    discover_lan_clients,
    discover_mesh_peers,
    discover_synergy_peers,
    match_discovered_peer,
)
from peplink_core.exceptions import PeplinkConfigError


def discovery_gateway_id(device: DeviceConfig, fleet: FleetConfig) -> str:
    if not device.discover:
        raise PeplinkConfigError("discovery_gateway_id called without discover config")
    gateway_id = device.discover.via or fleet.defaults.gateway_id
    if not gateway_id:
        raise PeplinkConfigError(
            "discover.via or defaults.gateway_id required for host discovery"
        )
    if gateway_id not in fleet.devices:
        raise PeplinkConfigError(f"unknown discovery gateway: {gateway_id}")
    return gateway_id


def build_read_only_client(fleet: FleetConfig, device_id: str) -> PeplinkDeviceClient:
    device = fleet.devices[device_id]
    if not device.host:
        raise PeplinkConfigError(f"devices.{device_id}.host required to build client")
    if device.auth is None or device.auth.read_only is None:
        raise PeplinkConfigError(f"devices.{device_id} read_only auth not configured")
    return PeplinkDeviceClient(
        device.base_url,
        device.auth.read_only,
        "read_only",
        verify_tls=device.verify_tls,
    )


def resolve_discovered_hosts(fleet: FleetConfig) -> None:
    """Fill host on devices configured with discover.* using gateway APIs."""
    pending = [
        (device_id, device)
        for device_id, device in fleet.devices.items()
        if device.discover is not None and not device.host
    ]
    if not pending:
        return

    mesh_cache: dict[str, list] = {}
    client_cache: dict[str, list] = {}
    synergy_cache: dict[str, list] = {}
    for device_id, device in pending:
        gateway_id = discovery_gateway_id(device, fleet)
        gateway = fleet.devices[gateway_id]
        if not gateway.host:
            raise PeplinkConfigError(
                f"devices.{gateway_id}.host required — gateway must have a static address"
            )
        client = build_read_only_client(fleet, gateway_id)
        if device.management == "gateway" and device.kind == "router":
            if gateway_id not in synergy_cache:
                synergy_cache[gateway_id] = discover_synergy_peers(
                    client, gateway_host=gateway.host
                )
            peers = synergy_cache[gateway_id]
        elif device.kind in ("ap", "switch"):
            if gateway_id not in client_cache:
                client_cache[gateway_id] = discover_lan_clients(client)
            peers = client_cache[gateway_id]
        else:
            if gateway_id not in mesh_cache:
                mesh_cache[gateway_id] = discover_mesh_peers(client)
            peers = mesh_cache[gateway_id]
        peer = match_discovered_peer(
            peers,
            device.discover.match,
            device_id=device_id,
        )
        device.host = peer.host
