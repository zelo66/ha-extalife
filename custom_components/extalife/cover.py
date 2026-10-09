"""Support for Exta Life roller shutters: SRP, SRM, ROB(future)"""
import logging
from enum import StrEnum
from typing import (
    Any,
    Mapping,
)

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
    ATTR_POSITION,
    DOMAIN as DOMAIN_COVER,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .helpers.const import (
    VIRTUAL_SENSOR_DEV_CLS,
    VIRTUAL_SENSOR_PATH,
    OPTIONS_COVER,
    OPTIONS_COVER_INVERTED_CONTROL,
    DOMAIN_VIRTUAL_COVER_SENSOR
)
from .helpers.core import Core
from .helpers.entities import ExtaLifeChannelNamed
from .pyextalife import (
    ExtaLifeAction,
    ExtaGateChannelType,
    ExtaGateChannelState,
    DEVICE_ARR_COVER,
    DEVICE_ARR_SENS_GATE_CONTROLLER
)
from .sensor import ExtaSensorDeviceClass


class ExtaCoverAction(StrEnum):
    NONE = ""
    CLOSING = "closing"
    OPENING = "opening"

_LOGGER = logging.getLogger(__name__)

# noinspection PyUnusedLocal
async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback) -> None:
    """Set up Exta Life covers based on existing config."""

    core: Core = Core.get(config_entry.entry_id)

    async def async_load_entities() -> None:

        channels: list[dict[str, Any]] = core.get_channels(DOMAIN_COVER)
        _LOGGER.debug(f"Discovery ({DOMAIN_COVER}): {channels}")
        if channels:
            async_add_entities([ExtaLifeCoverNamed(channel, config_entry) for channel in channels])

        core.pop_channels(DOMAIN_COVER)
        return None

    await core.platform_register(DOMAIN_COVER, async_load_entities)


class ExtaLifeCoverNamed(ExtaLifeChannelNamed, CoverEntity):
    """Representation of ExtaLife Cover"""

    def __init__(self, channel: dict[str, Any], config_entry: ConfigEntry):
        super().__init__(config_entry, channel)

        self._action: ExtaCoverAction = ExtaCoverAction.NONE
        self.push_virtual_sensor_channels(DOMAIN_VIRTUAL_COVER_SENSOR, channel)

    # Exta Life extreme cover positions
    POS_OPEN = 0
    POS_CLOSED = 100

    @property
    def is_gate( self ) ->  bool:
        return ( self.device_class == CoverDeviceClass.GATE ) or ( self.device_class == CoverDeviceClass.DOOR )

    @property
    def device_class(self) -> CoverDeviceClass:
        """Return the class of this device, from component DEVICE_CLASSES."""
        chn_type = self.channel_data.get("channel_type")
        if self.device_model in DEVICE_ARR_COVER:
            return CoverDeviceClass.SHUTTER
        elif chn_type == ExtaGateChannelType.WICKET:
            return CoverDeviceClass.DOOR
        else:
            return CoverDeviceClass.GATE

    @property
    def supported_features(self) -> CoverEntityFeature:
        """Flag supported features."""
        dev_type = self.channel_data.get("type")
        if not self.is_exta_free:
            if dev_type in DEVICE_ARR_COVER:
                features = (CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE |
                            CoverEntityFeature.SET_POSITION | CoverEntityFeature.STOP)
                return features
            elif dev_type in DEVICE_ARR_SENS_GATE_CONTROLLER:
                features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
                return features
        else:
            return CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

        return CoverEntityFeature(0)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        es_attr = self._mapping_to_dict( super().extra_state_attributes )

        channel_type = self.channel_data.get("channel_type")
        if channel_type is not None:
            es_attr.update( { "channel_type": channel_type })

        channel_state = self.channel_data.get("channel_state")
        if channel_state is not None:
            es_attr.update( { "channel_state": channel_state })

        return  es_attr

    @property
    def current_cover_position(self) -> int | None:
        """Return current position of cover. 0 is closed, 100 is open."""
        if self.is_exta_free or self.is_gate:
            return None

        val = self.channel_data.get("value")
        if val is None:
            return None
        return self._value_to_position(val)

    def _value_to_position(self, value: int) -> int:
        """Convert Exta Life value (0 = open, 100 = closed) to HA position (0 = closed, 100 = open)"""
        return value if self.is_inverted_control else 100 - value

    def _position_to_value(self, position: int) -> int:
        """Convert HA position (0 = closed, 100 = open) to Exta Life value (0 = open, 100 = closed)"""
        return position if self.is_inverted_control else 100 - position

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""
        if self.is_gate:
            return  None

        data = self.channel_data
        pos = int(kwargs.get(ATTR_POSITION))
        value = self._position_to_value(pos)

        _LOGGER.debug("set_cover_position for cover: %s. From HA: %s => value: %s", self.entity_id, pos, value)
        if await self.async_action(ExtaLifeAction.EXTA_LIFE_SET_POS, value=value):
            data["value"] = value
            self.async_schedule_update_ha_state()

        return None

    @property
    def is_inverted_control(self) -> bool:
        """Wherever to use inverted logic of open/close for 0-100"""
        return self.config_entry.options.get(OPTIONS_COVER, {}).get(OPTIONS_COVER_INVERTED_CONTROL, False)

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed (affects roller icon and entity status)."""
        pos = self.channel_data.get("value")
        gate_state = self.channel_data.get("channel_state")

        if pos is not None:
            if self.is_gate:
                return pos == ExtaLifeCoverNamed.POS_CLOSED
            # HA position 0 means closed (respects inverted control option)
            return self._value_to_position(pos) == 0

        if gate_state is not None:
            return gate_state == ExtaGateChannelState.CLOSED

        return None

    @property
    def virtual_sensors(self) -> list[dict[str, Any]]:
        result = super().virtual_sensors
        channel_state = self.data.get("channel_state")
        if channel_state is not None and channel_state != ExtaGateChannelState.NONE:
            result.append(
                    {
                        VIRTUAL_SENSOR_DEV_CLS: ExtaSensorDeviceClass.GATE_STATE,
                        VIRTUAL_SENSOR_PATH: "channel_state",
                    }
            )
        return result

    @property
    def is_closing( self ) -> bool | None:
        if self._action != ExtaCoverAction.NONE:
            return self._action == ExtaCoverAction.CLOSING
        return None

    @property
    def is_opening(self) -> bool | None:
        if self._action != ExtaCoverAction.NONE:
            return  self._action == ExtaCoverAction.OPENING
        return None

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        data = self.channel_data
        # ROB-21 to open 'pos' must be different from 0
        pos = 1 if self.is_gate else self._position_to_value(100)

        if not self.is_exta_free:
            if self.is_gate:
                action = ExtaLifeAction.EXTA_LIFE_GATE_POS
            else:
                action = ExtaLifeAction.EXTA_LIFE_SET_POS

            if await self.async_action(action, value=pos):
                if self.is_gate:
                    self._action = ExtaCoverAction.OPENING
                    _LOGGER.debug( f"open_cover for gate: {self.entity_id}. action: {self._action}" )
                else:
                    data["value"] = pos
                    _LOGGER.debug(f"open_cover for cover: {self.entity_id}. pos: {pos}")

                self.async_schedule_update_ha_state()
        else:
            if (await self.async_action(ExtaLifeAction.EXTA_FREE_UP_PRESS) and
                    await self.async_action(ExtaLifeAction.EXTA_FREE_UP_RELEASE)):
                self.async_schedule_update_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""

        data = self.channel_data
        pos = ExtaLifeCoverNamed.POS_CLOSED if self.is_gate else self._position_to_value(0)

        if not self.is_exta_free:
            if self.is_gate:
                action = ExtaLifeAction.EXTA_LIFE_GATE_POS
            else:
                action = ExtaLifeAction.EXTA_LIFE_SET_POS

            if await self.async_action(action, value=pos):
                if self.is_gate:
                    self._action = ExtaCoverAction.CLOSING
                    _LOGGER.debug( f"close_cover for gate: {self.entity_id}. action: {self._action}" )
                else:
                    data["value"] = pos
                    _LOGGER.debug(f"close_cover for cover: {self.entity_id}. pos: {pos}")

                self.async_schedule_update_ha_state()

        else:
            if (await self.async_action(ExtaLifeAction.EXTA_FREE_DOWN_PRESS) and
                    await self.async_action(ExtaLifeAction.EXTA_FREE_DOWN_RELEASE)):
                self.async_schedule_update_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        if self.is_gate:
            action = ExtaLifeAction.EXTA_LIFE_GATE_POS
        else:
            action = ExtaLifeAction.EXTA_LIFE_STOP

        await self.async_action( action, value= 1 if self.is_gate else 0 )

    def on_state_notification(self, data: dict[str, Any]) -> None:
        """ React on state notification from controller """
        super().on_state_notification(data)

        force_update = False

        ch_data = self.channel_data.copy()
        if ch_data.get("value") is not None:
            ch_data["value"] = data.get("value")

        if ch_data.get("channel_state") is not None:
            ch_data["channel_state"] = data.get("channel_state")
            force_update = self._action != ExtaCoverAction.NONE

        # update only if notification data contains new status; prevent HA event bus overloading
        if ch_data != self.channel_data or force_update:
            self._action = ExtaCoverAction.NONE
            self.channel_data.update(ch_data)
            # synchronize DataManager data with processed update & entity data
            self.sync_data_update_ha()
