"""Config-authority precedence + break-glass override tests."""

from __future__ import annotations

import pytest
from peplink_core.config import DeviceConfig, DeviceIC2Mapping
from peplink_core.config_authority import (
    ConfigAuthorityRedirect,
    plan_write_authority,
    preferred_authority,
)

SSID = "/api/config.ssid.profile"  # IC2-managed
DHCP = "/api/config.dhcp"  # not IC2-managed


def _dev(**kw) -> DeviceConfig:
    base = {"host": "10.0.0.1", "kind": "router"}
    base.update(kw)
    return DeviceConfig(**base)


def test_prefers_ic2_when_enabled_mapped_and_managed_path():
    dev = _dev(ic2=DeviceIC2Mapping(serial="S-1"))
    assert preferred_authority(dev, SSID, ic2_enabled=True) == "ic2"


def test_ic2_not_preferred_for_unmanaged_path():
    dev = _dev(ic2=DeviceIC2Mapping(serial="S-1"))
    assert preferred_authority(dev, DHCP, ic2_enabled=True) == "device"


def test_ic2_disabled_falls_through():
    dev = _dev(ic2=DeviceIC2Mapping(serial="S-1"))
    assert preferred_authority(dev, SSID, ic2_enabled=False) == "device"


def test_config_authority_device_pins_to_device():
    dev = _dev(ic2=DeviceIC2Mapping(serial="S-1"), config_authority="device")
    assert preferred_authority(dev, SSID, ic2_enabled=True) == "device"


def test_gateway_preferred_when_managed():
    dev = _dev(management="gateway", discover=None)
    assert preferred_authority(dev, SSID, ic2_enabled=False) == "gateway"


def test_ic2_outranks_gateway():
    dev = _dev(management="gateway", ic2=DeviceIC2Mapping(serial="S-1"))
    assert preferred_authority(dev, SSID, ic2_enabled=True) == "ic2"


# -- plan_write_authority (override / break-glass) --


def test_ic2_preferred_without_override_redirects():
    dev = _dev(ic2=DeviceIC2Mapping(serial="S-1"))
    with pytest.raises(ConfigAuthorityRedirect) as exc:
        plan_write_authority(dev, SSID, ic2_enabled=True, override=None)
    assert exc.value.ic2_tool == "peplink_ic2_put_ssid_settings"


def test_ic2_break_glass_to_device():
    dev = _dev(ic2=DeviceIC2Mapping(serial="S-1"))
    plan = plan_write_authority(dev, SSID, ic2_enabled=True, override="device")
    assert (plan.level, plan.preferred, plan.overridden) == ("device", "ic2", True)


def test_ic2_break_glass_to_gateway():
    dev = _dev(ic2=DeviceIC2Mapping(serial="S-1"), management="gateway")
    plan = plan_write_authority(dev, SSID, ic2_enabled=True, override="gateway")
    assert plan.level == "gateway" and plan.overridden is True


def test_gateway_break_glass_to_device():
    dev = _dev(management="gateway")
    plan = plan_write_authority(dev, SSID, ic2_enabled=False, override="device")
    assert (plan.level, plan.preferred, plan.overridden) == ("device", "gateway", True)


def test_device_preferred_is_noop():
    dev = _dev()
    plan = plan_write_authority(dev, DHCP, ic2_enabled=True, override=None)
    assert plan.level == "device" and plan.overridden is False


def test_invalid_override_rejected():
    dev = _dev(ic2=DeviceIC2Mapping(serial="S-1"))
    with pytest.raises(ValueError):
        plan_write_authority(dev, SSID, ic2_enabled=True, override="ic2")
