"""Registry behavior for SNMP-only AP devices."""

import pytest
from peplink_core.config import DeviceConfig, FleetConfig
from peplink_core.exceptions import PeplinkConfigError
from peplink_core.registry import DeviceRegistry
from peplink_core.snmp.client import SnmpConfig


def test_registry_snmp_only_ap_raises_helpful_error():
    fleet = FleetConfig(
        devices={
            "ap1": DeviceConfig(
                host="10.0.0.200",
                kind="ap",
                snmp=SnmpConfig(community="public"),
            ),
        },
    )
    registry = DeviceRegistry(fleet)
    with pytest.raises(PeplinkConfigError, match="SNMP-only"):
        registry.get("ap1")
