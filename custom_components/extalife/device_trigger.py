"""Provides device automations for Exta Life."""
from __future__ import annotations

import logging
from typing import (
    Any,
)

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_PLATFORM,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .helpers.const import (
    DOMAIN,
    CONF_EXTALIFE_EVENT_TRANSMITTER,
    CONF_EXTALIFE_EVENT_UNIQUE_ID,
    TRIGGER_TYPE,
    TRIGGER_SUBTYPE,
)
from .helpers.compat import device_config_entry_ids
from .helpers.typing import DeviceType

_LOGGER = logging.getLogger(__name__)


TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {vol.Required(TRIGGER_TYPE): str, vol.Required(TRIGGER_SUBTYPE): str}
)


async def _async_get_device(hass: HomeAssistant, device_id: str) -> DeviceType | None:
    """Resolve Exta Life device object for HA Device Registry id"""
    from .helpers.core import Core

    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None

    for entry_id in device_config_entry_ids(device):
        core = Core.get(entry_id)
        if core:
            return await core.device_manager.async_get_by_registry_id(device.id)

    return None


async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict[str, Any]]:
    """List device triggers for Exta Life devices."""

    _LOGGER.debug("async_get_triggers() device_id: %s", device_id)

    int_device = await _async_get_device(hass, device_id)
    if int_device is None:
        return []

    return [
        {
            CONF_PLATFORM: "device",
            CONF_DEVICE_ID: device_id,
            CONF_DOMAIN: DOMAIN,
            TRIGGER_TYPE: trigger.get(TRIGGER_TYPE),
            TRIGGER_SUBTYPE: trigger.get(TRIGGER_SUBTYPE)
        }
        for trigger in int_device.triggers
    ]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a trigger to an automation"""

    _LOGGER.debug("async_attach_trigger() config: %s", config)

    # Transmitters are discovered only after connection to the controller is established, so during
    # HA startup the device may not be known yet. The event unique id is the device identifier stored
    # in Device Registry, so the trigger can be attached without waiting for the discovery.
    device = dr.async_get(hass).async_get(config[CONF_DEVICE_ID])
    if device is None:
        raise HomeAssistantError(f"Exta Life device {config[CONF_DEVICE_ID]} does not exist in Device Registry")

    unique_id = next((identifier[1] for identifier in device.identifiers if identifier[0] == DOMAIN), None)

    # we'll use event platform as the one to listen to the device trigger
    event_config = {
        event.CONF_PLATFORM: "event",
        event.CONF_EVENT_TYPE: CONF_EXTALIFE_EVENT_TRANSMITTER,
        event.CONF_EVENT_DATA: {
            CONF_EXTALIFE_EVENT_UNIQUE_ID: unique_id,
            TRIGGER_TYPE: config[TRIGGER_TYPE],
            TRIGGER_SUBTYPE: config[TRIGGER_SUBTYPE],
        },
    }

    _LOGGER.debug("async_attach_trigger() event_config: %s", event_config)

    event_config = event.TRIGGER_SCHEMA(event_config)

    return await event.async_attach_trigger(hass, event_config, action, trigger_info, platform_type="device")
