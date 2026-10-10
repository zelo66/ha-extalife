"""Support for Exta Life binary sensor devices e.g. leakage sensor, door/window open sensor"""
import logging
from typing import (
    Any
)
from collections.abc import Mapping

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    DOMAIN as DOMAIN_BINARY_SENSOR
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .helpers.const import (
    CONTROLLER_DATA,
    DOMAIN_VIRTUAL_BINARY_SENSOR_SENSOR,
    RESPONDING_DATA,
    SIGNAL_CONTROLLER_STATE_UPDATED,
)
from .helpers.core import Core
from .helpers.entities import ExtaLifeChannelNamed, ExtaLifeDevice
from .pyextalife import (  # pylint: disable=syntax-error
    DEVICE_ARR_SENS_WATER,
    DEVICE_ARR_SENS_MOTION,
    DEVICE_ARR_SENS_OPEN_CLOSE,
)

_LOGGER = logging.getLogger(__name__)


# noinspection PyUnusedLocal
async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback) -> None:
    """Set up Exta Life binary sensors based on existing config."""

    core: Core = Core.get(config_entry.entry_id)

    async def async_load_entities() -> None:

        channels: list[dict[str, Any]] = core.get_channels(DOMAIN_BINARY_SENSOR)
        _LOGGER.debug("Discovery: (%s): %s", DOMAIN_BINARY_SENSOR, channels)
        if channels:
            entities: list[BinarySensorEntity] = []
            for channel in channels:
                if channel.get(CONTROLLER_DATA):
                    entities.append(ExtaLifeControllerConnectivity(config_entry, channel))
                elif channel.get(RESPONDING_DATA):
                    entities.append(ExtaLifeChannelResponding(channel, config_entry))
                else:
                    entities.append(ExtaLifeBinarySensorNamed(channel, config_entry))
            async_add_entities(entities)

        core.pop_channels(DOMAIN_BINARY_SENSOR)
        return None

    await core.platform_register(DOMAIN_BINARY_SENSOR, async_load_entities)


class ExtaLifeBinarySensorNamed(ExtaLifeChannelNamed, BinarySensorEntity):
    """Representation of an ExtaLife binary sensors"""

    def __init__(self, channel, config_entry: ConfigEntry):
        super().__init__(config_entry, channel)

        self.push_virtual_sensor_channels(DOMAIN_VIRTUAL_BINARY_SENSOR_SENSOR, channel)

    @property
    def is_on(self) -> bool | None:
        """Return state of the sensor"""

        # Exta Life detection sensors keep their boolean status in field value_3
        state = self.channel_data.get("value_3")

        if self.device_model in DEVICE_ARR_SENS_WATER:
            value = state

        elif self.device_model in DEVICE_ARR_SENS_MOTION:
            value = state

        elif self.device_model in DEVICE_ARR_SENS_OPEN_CLOSE:
            value = None if state is None else not state
        else:
            value = state

        return None if value is None else bool(value)

    @property
    def device_class(self) -> str | None:
        """Return the class of this device, from component DEVICE_CLASSES."""
        if self.device_model in DEVICE_ARR_SENS_WATER:
            return BinarySensorDeviceClass.MOISTURE

        if self.device_model in DEVICE_ARR_SENS_MOTION:
            return BinarySensorDeviceClass.MOTION

        if self.device_model in DEVICE_ARR_SENS_OPEN_CLOSE:
            return BinarySensorDeviceClass.OPENING

        return super().device_class

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return device specific state attributes."""
        es_attr: dict[str, Any] = self._mapping_to_dict(super().extra_state_attributes)
        ch_data: dict[str, Any] = self.channel_data

        # general sensor attributes
        self._extra_state_attribute_update(ch_data, es_attr, "sync_time")
        self._extra_state_attribute_update(ch_data, es_attr, "last_sync")

        # motion sensor attributes
        if self.device_class == BinarySensorDeviceClass.MOTION:
            es_attr.update({"tamper": ch_data.get("tamper")})
            es_attr.update({"tamper_sync_time": ch_data.get("tamper_sync_time")})

        return es_attr

    def on_state_notification(self, data: dict[str, Any]) -> None:
        """ React on state notification from controller """

        super().on_state_notification(data)

        state = data.get("state")
        ch_data = self.channel_data.copy()

        ch_data["value_3"] = state

        _LOGGER.debug(
            "on_state_notification for entity: %s, id: %s. Status to be updated: %s",
            self.entity_id, self.channel_id, state,
        )

        # update only if notification data contains new status; prevent HS event bus overloading
        if ch_data != self.channel_data:
            self.channel_data.update(ch_data)

            # synchronize DataManager data with processed update & entity data
            self.sync_data_update_ha()


class ExtaLifeControllerConnectivity(ExtaLifeDevice, BinarySensorEntity):
    """Connection state between Home Assistant and EFC-01 controller"""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, config_entry: ConfigEntry, device_data: dict[str, Any]) -> None:
        super().__init__(config_entry, device_data)
        self._attr_translation_key = "controller_connection"

    def _get_unique_id(self) -> str:
        return f"{super()._get_unique_id()}-connectivity"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.core.async_signal_register(SIGNAL_CONTROLLER_STATE_UPDATED, self.async_write_ha_state)
        )

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.controller.is_connected


class ExtaLifeChannelResponding(ExtaLifeChannelNamed, BinarySensorEntity):
    """Diagnostic sensor: the device responds to the controller over radio (controller 'is_timeout' flag).

    Unlike the main entity of the channel it stays available when the device is not responding, so the
    history shows when the device was out of reach and automations can react to it."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, channel: dict[str, Any], config_entry: ConfigEntry) -> None:
        super().__init__(config_entry, channel)
        self._attr_translation_key = "channel_responding"

    def _get_unique_id(self) -> str:
        return f"{super()._get_unique_id()}-responding"

    @property
    def name(self) -> str | None:
        # device may have several channels - name the sensor after the channel alias
        alias = self.channel_data.get("alias")
        return f"{alias} responding" if alias else "Responding"

    @property
    def available(self) -> bool:
        return self.data_available

    @property
    def is_on(self) -> bool | None:
        is_timeout = self.channel_data.get("is_timeout")
        if is_timeout is None:
            return None
        return not is_timeout

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return {"channel_id": self.channel_id}
