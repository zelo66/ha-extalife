"""Diagnostics support for Exta Life integration."""
from __future__ import annotations

import logging
from typing import Any
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .helpers.const import DOMAIN, TO_REDACT
from .helpers.core import Core
from .pyextalife import (
    ExtaLifeDataList,
)

_LOGGER = logging.getLogger(__name__)


def _controller_info(core: Core) -> dict[str, Any]:
    api = core.api
    return {
        "connected": api.is_connected,
        "host": api.host,
        "port": api.port,
        "mac": api.mac,
        "name": api.name,
        "version_installed": api.version_installed,
        "version_web": api.version_web,
        "network": dict(api.network),
        "recv_timeout": api.recv_timeout,
        "control_commands": api.control_stats.as_dict(),
        "all_commands": api.command_stats.as_dict(),
    }


# noinspection PyUnusedLocal
async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    core: Core = Core.get(config_entry.entry_id)
    backup: ExtaLifeDataList | None = await core.api.async_get_config_backup() if core else None
    return {
        "entry": {
            "data": async_redact_data(config_entry.data, TO_REDACT),
            "options": async_redact_data(config_entry.options, TO_REDACT),
        },
        "controller": _controller_info(core) if core else None,
        "controller_config": async_redact_data(backup, TO_REDACT) if backup else []
    }


# noinspection PyUnusedLocal
async def async_get_device_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for a device: raw channel data as reported by the controller.

    This is what is needed to add support for a new device model."""
    core: Core = Core.get(config_entry.entry_id)
    identifiers = {identifier[1] for identifier in device.identifiers if identifier[0] == DOMAIN}
    result: dict[str, Any] = {
        "device": {
            "name": device.name,
            "model": device.model,
            "identifiers": sorted(str(identifier) for identifier in identifiers),
        },
    }
    if core is None:
        return result

    if core.api.mac in identifiers:
        result["controller"] = _controller_info(core)
        return result

    # device identifiers are serial numbers (int for transmitters, str for channel entities)
    serials = {str(identifier) for identifier in identifiers}
    channels = {
        channel_id: channel_data
        for channel_id, channel_data in core.channel_manager.channels_get().items()
        if str(channel_data.get("serial")) in serials
    }
    device_ids = {channel_data.get("id") for channel_data in channels.values()}
    result["channels"] = async_redact_data(channels, TO_REDACT)
    result["device_config"] = async_redact_data(
        {
            str(device_id): core.channel_manager.device_get_data(device_id)
            for device_id in device_ids
            if core.channel_manager.device_get_data(device_id) is not None
        },
        TO_REDACT,
    )
    return result
