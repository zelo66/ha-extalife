"""Support for Exta Life events: transmitter (remote, wall switch) buttons and controller scenes"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.event import (
    DOMAIN as DOMAIN_EVENT,
    EventDeviceClass,
    EventEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .helpers.compat import via_device_info
from .helpers.const import (
    CONF_EXTALIFE_EVENT_SCENE,
    CONF_EXTALIFE_EVENT_TRANSMITTER,
    CONF_EXTALIFE_EVENT_UNIQUE_ID,
    CONTROLLER_DATA,
    DOMAIN,
    TRIGGER_SUBTYPE,
    TRIGGER_SUBTYPE_BUTTON_TEMPLATE,
    TRIGGER_TYPE,
)
from .helpers.core import Core
from .helpers.device import TRANSMITTER_TRIGGER_TYPES, transmitter_button_count
from .helpers.entities import ExtaLifeChannel, ExtaLifeDevice
from .pyextalife import (
    PRODUCT_MANUFACTURER,
    ExtaLifeDeviceModel,
)

_LOGGER = logging.getLogger(__name__)

EVENT_SCENE_ACTIVATED = "scene_activated"


# noinspection PyUnusedLocal
async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback) -> None:
    """Set up Exta Life event entities based on existing config."""

    core: Core = Core.get(config_entry.entry_id)

    async def async_load_entities() -> None:
        items: list[dict[str, Any]] = core.get_channels(DOMAIN_EVENT) or []
        _LOGGER.debug("Discovery (%s): %s", DOMAIN_EVENT, items)

        entities: list[EventEntity] = []
        for item in items:
            if item.get(CONTROLLER_DATA):
                entities.append(ExtaLifeSceneEvent(config_entry, item))
                continue

            device_type = ExtaLifeDeviceModel(item["data"]["type"])
            for button in range(1, transmitter_button_count(device_type) + 1):
                entities.append(ExtaLifeTransmitterButtonEvent(config_entry, item, button))

        if entities:
            async_add_entities(entities)

        core.pop_channels(DOMAIN_EVENT)

    await core.platform_register(DOMAIN_EVENT, async_load_entities)


class ExtaLifeTransmitterButtonEvent(ExtaLifeChannel, EventEntity):
    """Single button of a transmitter. Fires press, release and gesture (click, long press) events"""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = list(TRANSMITTER_TRIGGER_TYPES)

    def __init__(self, config_entry: ConfigEntry, channel: dict[str, Any], button: int) -> None:
        super().__init__(config_entry, channel)
        self._button = button
        self._subtype = TRIGGER_SUBTYPE_BUTTON_TEMPLATE.format(button)
        self._attr_translation_key = "transmitter_button"
        self._attr_translation_placeholders = {"button": str(button)}

    def _get_unique_id(self) -> str:
        return f"{super()._get_unique_id()}-{self._subtype}"

    @property
    def device_info(self) -> DeviceInfo | None:
        # transmitters are registered in Device Registry by TransmitterManager with numeric serial identifier
        serial_no: int = self.data.get("serial", 0)
        device_info = DeviceInfo(
            identifiers={(DOMAIN, serial_no)},
            name=str(self.device_model_name),
            manufacturer=PRODUCT_MANUFACTURER,
            model=str(self.device_model_name),
            serial_number=f"{serial_no:06X} ({serial_no})",
        )
        device_info.update(
            via_device_info(self.core.hass, (DOMAIN, self.controller.mac), self.config_entry.entry_id)
        )
        return device_info

    @property
    def available(self) -> bool:
        return self.controller.is_connected

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(CONF_EXTALIFE_EVENT_TRANSMITTER, self._async_handle_transmitter_event)
        )

    @callback
    def _async_handle_transmitter_event(self, event: Event) -> None:
        data = event.data
        if data.get(CONF_EXTALIFE_EVENT_UNIQUE_ID) != self.data.get("serial"):
            return
        if data.get(TRIGGER_SUBTYPE) != self._subtype:
            return
        event_type = data.get(TRIGGER_TYPE)
        if event_type not in self._attr_event_types:
            return

        self._trigger_event(event_type)
        self.async_write_ha_state()


class ExtaLifeSceneEvent(ExtaLifeDevice, EventEntity):
    """Scene activated on the controller (e.g. from Exta Life app or a transmitter)"""

    _attr_event_types = [EVENT_SCENE_ACTIVATED]

    def __init__(self, config_entry: ConfigEntry, device_data: dict[str, Any]) -> None:
        super().__init__(config_entry, device_data)
        self._attr_translation_key = "scene"

    def _get_unique_id(self) -> str:
        return f"{super()._get_unique_id()}-scene"

    @property
    def available(self) -> bool:
        return self.controller.is_connected

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(CONF_EXTALIFE_EVENT_SCENE, self._async_handle_scene_event)
        )

    @callback
    def _async_handle_scene_event(self, event: Event) -> None:
        # event attributes must be JSON serializable - keep only simple values
        attributes = {
            key: value for key, value in event.data.items()
            if isinstance(value, (str, int, float, bool)) or value is None
        }
        self._trigger_event(EVENT_SCENE_ACTIVATED, attributes)
        self.async_write_ha_state()
