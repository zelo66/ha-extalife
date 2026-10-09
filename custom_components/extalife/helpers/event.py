import logging
from datetime import datetime

from homeassistant.const import (
    CONF_TYPE
)
from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later

from .const import (
    CONF_EXTALIFE_EVENT_UNIQUE_ID,
    CONF_PROCESSOR_EVENT_STAT_NOTIFICATION,
    CONF_PROCESSOR_EVENT_UNKNOWN,
    EVENT_TIMESTAMP,
    EVENT_DATA,
    TRIGGER_BUTTON_LONG_PRESS,
    TRIGGER_BUTTON_DOUBLE_CLICK,
    TRIGGER_BUTTON_DOWN,
    TRIGGER_BUTTON_UP,
    TRIGGER_BUTTON_SINGLE_CLICK,
    TRIGGER_SUBTYPE_BUTTON_TEMPLATE,
    TRIGGER_BUTTON_TRIPLE_CLICK,
    TRIGGER_SUBTYPE, TRIGGER_TYPE
)
from .core import Core
from .device import Device
from ..pyextalife import DEVICE_ARR_ALL_TRANSMITTER

_LOGGER = logging.getLogger(__name__)


class ExtaLifeEventProcessor:
    """ Processes status notification events from controller """
    def __init__(self, device: Device):
        self._device = device

    @staticmethod
    def factory(device: Device) -> 'ExtaLifeTransmitterEventProcessor':
        if device.type in DEVICE_ARR_ALL_TRANSMITTER:
            return ExtaLifeTransmitterEventProcessor(device)

    def process_event(self, data: dict, event_type=CONF_PROCESSOR_EVENT_UNKNOWN):
        if event_type == CONF_PROCESSOR_EVENT_UNKNOWN:
            raise NotImplementedError()


class ExtaLifeTransmitterEventProcessor(ExtaLifeEventProcessor):
    def __init__(self, device: Device):
        super().__init__(device)
        self._device = device
        self._event_data = dict()
        self._event_window = dict()
        self._window_timers: dict = {}

    def shutdown(self) -> None:
        """Cancel pending gesture detection timers (e.g. when config entry is unloaded)"""
        for cancel in self._window_timers.values():
            cancel()
        self._window_timers = {}
        self._event_window = {}

    def check_supported(self, event_type):
        if event_type != CONF_PROCESSOR_EVENT_STAT_NOTIFICATION:
            raise NotImplementedError()

    @staticmethod
    def encapsulate(event_data) -> dict:
        event = dict()
        event[EVENT_TIMESTAMP] = datetime.now()
        event[EVENT_DATA] = event_data
        return event

    # time window in which button presses are combined into single / double / triple click
    CLICK_WINDOW_SECONDS = 0.6

    def process_event(self, data, event_type=CONF_PROCESSOR_EVENT_UNKNOWN):
        _LOGGER.debug("process_event data: %s", data)
        super().process_event(data, event_type)
        self.check_supported(event_type)

        hass = Core.get_hass()

        # assumption: data fields in JSON protocol: button & state
        button = data.get('button')
        state = data.get('state')

        event_data = {
            CONF_EXTALIFE_EVENT_UNIQUE_ID: self._device.event.unique_id,
            TRIGGER_SUBTYPE: TRIGGER_SUBTYPE_BUTTON_TEMPLATE.format(button),
            CONF_TYPE: TRIGGER_BUTTON_DOWN if state == 1 else TRIGGER_BUTTON_UP,
        }

        # noinspection PyUnusedLocal
        @callback
        def _timeout_callback(now=None) -> None:
            # assumption: state = 0 or 1
            self._window_timers.pop(button, None)
            events = self._event_window.pop(button, None) or []
            value = ''.join(str(event[EVENT_DATA].get('state')) for event in events)

            _LOGGER.debug("_timeout_callback button: %s, value: %s", button, value)

            gesture_type = {
                '1': TRIGGER_BUTTON_LONG_PRESS,
                '10': TRIGGER_BUTTON_SINGLE_CLICK,
                '1010': TRIGGER_BUTTON_DOUBLE_CLICK,
                '101010': TRIGGER_BUTTON_TRIPLE_CLICK,
            }.get(value)

            if gesture_type:
                gesture_data = {
                    CONF_EXTALIFE_EVENT_UNIQUE_ID: self._device.event.unique_id,
                    TRIGGER_SUBTYPE: TRIGGER_SUBTYPE_BUTTON_TEMPLATE.format(button),
                    TRIGGER_TYPE: gesture_type,
                }
                # raise event to HA event bus
                _LOGGER.debug("_timeout_callback.async_fire event_data: %s", gesture_data)
                hass.bus.async_fire(self._device.event.event, event_data=gesture_data)

        window = self._event_window.get(button)
        if window is None:
            # first event for the button opens new time window (maximum triple click)
            window = []
            self._event_window[button] = window
            self._window_timers[button] = async_call_later(hass, self.CLICK_WINDOW_SECONDS, _timeout_callback)

        window.append(self.encapsulate(data))

        _LOGGER.debug("process_event.async_fire event_data: %s", event_data)
        hass.bus.async_fire(self._device.event.event, event_data=event_data)
