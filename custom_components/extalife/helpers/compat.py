"""Compatibility layer for differences between supported Home Assistant versions."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntry, DeviceInfo

# HA 2026.8 replaced DeviceInfo 'via_device' (identifier tuple) with 'via_device_id' (registry id)
DEVICE_INFO_VIA_DEVICE_ID: bool = "via_device_id" in DeviceInfo.__annotations__


def async_get_device_by_identifier(
        hass: HomeAssistant, identifier: tuple[str, Any], config_entry_id: str
) -> DeviceEntry | None:
    """Get device owned by the config entry by its identifier"""

    registry = dr.async_get(hass)
    get_by_identifier = getattr(registry, "async_get_device_by_identifier", None)
    if get_by_identifier is not None:
        # HA 2026.8+: identifiers are unique only within a config entry
        return get_by_identifier(identifier, config_entry_id)

    return registry.async_get_device(identifiers={identifier})


def via_device_info(hass: HomeAssistant, via_identifier: tuple[str, Any], config_entry_id: str) -> dict[str, Any]:
    """Build DeviceInfo fields linking a device with its parent (via) device"""

    if not DEVICE_INFO_VIA_DEVICE_ID:
        return {"via_device": via_identifier}

    via_device = async_get_device_by_identifier(hass, via_identifier, config_entry_id)
    if via_device is None:
        return {}
    return {"via_device_id": via_device.id}


def device_config_entry_ids(device: DeviceEntry) -> list[str]:
    """Return ids of config entries the device belongs to"""

    # HA 2026.8+: a device belongs to a single config entry
    config_entry_id = getattr(device, "config_entry_id", None)
    if config_entry_id is not None:
        return [config_entry_id]
    return list(device.config_entries)
