""" definition of all services for this integration """
import logging
import os.path
from datetime import timedelta

import voluptuous as vol
from homeassistant.const import CONF_ENTITY_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    entity_registry as er,
)
from homeassistant.helpers.entity_registry import (
    RegistryEntry,
)
from homeassistant.helpers.service import async_register_admin_service

from .const import (
    CONF_BACKUP_PATH,
    CONF_BACKUP_SCHEDULE,
    CONF_BACKUP_RETENTION,
    DEFAULT_RECORDING_MINUTES,
    DOMAIN,
)
from .typing import CoreType

# services
SVC_RESTART = "restart"  # restart controller
SVC_TEST_BUTTON = "test_button"
SVC_REFRESH_STATE = "refresh_state"  # execute status refresh, fetch new status from controller
SVC_CONFIG_BACKUP = "config_backup"  # create controller configuration backup
SVC_RECORD_TRAFFIC = "record_traffic"  # record traffic exchanged with controller

ATTR_DURATION = "duration"

_LOGGER = logging.getLogger(__name__)

SCHEMA_BASE = vol.Schema(
    {
        vol.Required(CONF_ENTITY_ID): cv.entity_id,
    }
)
SCHEMA_REFRESH_STATE = SCHEMA_RESTART = SCHEMA_BASE

SCHEMA_CONFIG_BACKUP = vol.Schema(
    {
        vol.Required(CONF_ENTITY_ID): cv.entity_id,
        vol.Optional(CONF_BACKUP_PATH, default=""): vol.Any(None, cv.string),
        vol.Optional(CONF_BACKUP_SCHEDULE, default=""): vol.Any(None, cv.string),
        vol.Optional(CONF_BACKUP_RETENTION, default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
    }
)

SCHEMA_RECORD_TRAFFIC = vol.Schema(
    {
        vol.Required(CONF_ENTITY_ID): cv.entity_id,
        # minutes, 0 stops current recording
        vol.Optional(ATTR_DURATION, default=DEFAULT_RECORDING_MINUTES): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=180)
        ),
    }
)

SCHEMA_TEST_BUTTON = vol.Schema(
    {
        vol.Required(CONF_ENTITY_ID): cv.entity_id,
        vol.Required('button'): cv.string,
        vol.Required('channel_id'): cv.string,
        vol.Required('event'): vol.In(['single', 'double', 'triple', 'down', 'up']),
    }
)


class ExtaLifeServices:
    """ handle Exta Life services """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass: HomeAssistant = hass
        self._services: list[str] = []

    def _get_entry(self, entity_id: str) -> RegistryEntry | None:
        """ Resolve entity registry entry for entity_id """
        return er.async_get(self._hass).async_get(entity_id)

    def _get_core(self, entity_id: str) -> CoreType:
        """ Resolve the Core helper class for an entity, raise error if not possible """
        from .core import Core

        entry = self._get_entry(entity_id)
        if entry is None or entry.platform != DOMAIN:
            raise ServiceValidationError(f"Entity {entity_id} is not an Exta Life entity")

        core = Core.get(entry.config_entry_id)
        if core is None or core.api is None:
            raise ServiceValidationError(f"Exta Life integration for entity {entity_id} is not loaded")

        return core

    async def async_register_services(self) -> None:
        """ register all Exta Life integration services """

        def register_service(name: str, entry, schema: vol.Schema, admin: bool = False) -> None:
            if admin:
                # restart and writing files to arbitrary location are allowed only for administrators
                async_register_admin_service(self._hass, DOMAIN, name, entry, schema)
            else:
                self._hass.services.async_register(DOMAIN, name, entry, schema)
            self._services.append(name)

        register_service(SVC_RESTART, self._async_handle_restart, SCHEMA_RESTART, admin=True)
        register_service(SVC_REFRESH_STATE, self._async_handle_refresh_state, SCHEMA_REFRESH_STATE)
        register_service(SVC_TEST_BUTTON, self._async_handle_test_button, SCHEMA_TEST_BUTTON)
        register_service(SVC_CONFIG_BACKUP, self._async_handle_config_backup, SCHEMA_CONFIG_BACKUP, admin=True)
        register_service(SVC_RECORD_TRAFFIC, self._async_handle_record_traffic, SCHEMA_RECORD_TRAFFIC, admin=True)

    async def async_unregister_services(self) -> None:
        """ Unregister all Exta Life integration services """
        for service in self._services:
            self._hass.services.async_remove(DOMAIN, service)
        self._services = []

    async def _async_handle_restart(self, call: ServiceCall) -> None:
        """ service: 'extalife.restart' """
        core = self._get_core(call.data[CONF_ENTITY_ID])
        await core.api.async_restart()

    async def _async_handle_refresh_state(self, call: ServiceCall) -> None:
        """ service: extalife.refresh_state """
        core = self._get_core(call.data[CONF_ENTITY_ID])
        await core.channel_manager.async_status_polling_task_setup()

    def _get_backup_path(self, path: str | None) -> str:
        if not path:
            return self._hass.config.path(DOMAIN)
        elif not os.path.isabs(path):
            return self._hass.config.path(DOMAIN, path)
        return path

    async def _async_handle_config_backup(self, call: ServiceCall) -> None:
        """ service: extalife.config_backup - store controller configuration backup in files """
        core = self._get_core(call.data[CONF_ENTITY_ID])

        path: str = self._get_backup_path(call.data.get(CONF_BACKUP_PATH))

        await core.api.async_config_backup(
            path,
            schedule=call.data.get(CONF_BACKUP_SCHEDULE) or "",
            retention=call.data.get(CONF_BACKUP_RETENTION, 0)
        )

    async def _async_handle_record_traffic(self, call: ServiceCall) -> None:
        """ service: extalife.record_traffic - record traffic exchanged with controller to a file """
        core = self._get_core(call.data[CONF_ENTITY_ID])
        duration: int = call.data[ATTR_DURATION]

        if duration == 0:
            await core.async_stop_recording()
            return

        await core.async_start_recording(timedelta(minutes=duration))

    async def _async_handle_test_button(self, call: ServiceCall) -> None:
        """ service: extalife.test_button - simulate transmitter button events """
        from .common import PseudoPlatform

        button = call.data.get('button')
        channel_id = call.data.get('channel_id')
        event = call.data.get('event')

        core = self._get_core(call.data[CONF_ENTITY_ID])

        signal = PseudoPlatform.get_notif_upd_signal(channel_id)

        num = 0

        def click() -> None:
            nonlocal num
            seq = 1
            num += 1
            signal_data = {"button": button, 'click': num, 'sequence': seq, 'state': 1}
            core.async_signal_send(signal, signal_data)

            signal_data = signal_data.copy()
            seq += 1
            signal_data['state'] = 0
            signal_data['sequence'] = seq

            core.async_signal_send(signal, signal_data)

        if event == 'triple':
            click()
            click()
            click()

        elif event == 'double':
            click()
            click()

        elif event == 'single':
            click()

        elif event == 'down':
            core.async_signal_send(signal, {'button': button, 'state': 1})

        elif event == 'up':
            core.async_signal_send(signal, {'button': button, 'state': 0})
