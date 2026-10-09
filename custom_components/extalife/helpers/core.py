import asyncio
import importlib
import inspect
import logging
from contextlib import suppress
from datetime import (
    datetime,
    timedelta
)
from typing import (
    Any,
)
from collections.abc import Awaitable, Callable

import homeassistant.const
from homeassistant.components.logbook import async_log_entry
from homeassistant.components.persistent_notification import async_create as async_create_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import Entity
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.translation import async_get_translations
from homeassistant.loader import (
    Integration,
)

from .const import (
    DATA_CORE,
    DOMAIN,
    CONF_EXTALIFE_EVENT_SCENE,
    CONTROLLER_OFFLINE_ISSUE_DELAY,
    ISSUE_CONTROLLER_OFFLINE,
    SIGNAL_CONTROLLER_STATE_UPDATED,
    URL_CHANGELOG_JSON,
)
from .typing import (
    ChannelDataManagerType,
    CoreType,
    DeviceManagerType,
    ExtaLifeControllerType
)
from ..pyextalife import (
    ExtaLifeAPI,
    ExtaLifeCmd,
    ExtaLifeResponse
)

MAP_NOTIF_CMD_TO_EVENT = {
    ExtaLifeCmd.ACTIVATE_SCENE: CONF_EXTALIFE_EVENT_SCENE
}

_LOGGER = logging.getLogger(__name__)


class Core:
    _inst: dict[str, CoreType] = dict()
    _hass: HomeAssistant = None
    _stop_listener_registered: bool = False

    _is_stopping = False

    @classmethod
    def create(cls, hass: HomeAssistant, integration: Integration, config_entry: ConfigEntry) -> CoreType:
        """Create Core instance for a given Config Entry"""
        if cls._hass is not hass:
            # new Home Assistant instance (e.g. tests) - reset class wide state
            cls._is_stopping = False
            cls._stop_listener_registered = False
        cls._hass = hass
        inst = Core(integration, config_entry)

        hass.data[DOMAIN][DATA_CORE] = cls._inst

        # register callback for HomeAssistant Stop event, but only once for all config entries
        if not cls._stop_listener_registered:
            cls._hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, cls._on_homeassistant_stop)
            cls._stop_listener_registered = True
        return inst

    @classmethod
    def get(cls, config_entry_id: str) -> CoreType:  # forward
        """Get instance of the Core object based on Config Entry ID"""
        return cls._inst.get(config_entry_id)

    @classmethod
    def get_hass(cls) -> HomeAssistant:
        """Return HomeAssistant instance"""
        return cls._hass

    def __init__(self, integration: Integration, config_entry: ConfigEntry):
        """initialize instance"""
        from .device import DeviceManager
        from ..transmitter import TransmitterManager
        from .. import ChannelDataManager

        self._integration = integration
        self._ver_check_web: bool = False
        self._inst[config_entry.entry_id] = self
        self._changelog: dict[str, Any] = {"next": 0, "data": []}
        self._config_entry: ConfigEntry = config_entry
        self._device_manager: DeviceManager = DeviceManager(config_entry, self)
        self._transmitter_manager = TransmitterManager(config_entry)
        self._api = ExtaLifeAPI(
            self.hass.loop,
            on_connect_callback=self._on_api_connect_callback,
            on_disconnect_callback=self._on_api_disconnect_callback,
            on_notification_callback=self._on_api_notification_callback
        )

        self._signal_callbacks: dict[str, Callable[[], None]] = {}
        self._track_time_callbacks: list[Callable] = []
        self._platforms: dict[str, list[dict[str, Any]]] = {}
        self._platform_loader: dict[str, Callable[[], Awaitable]] = {}
        self._platforms_cust: dict[str, list[dict[str, Any]]] = {}
        self._channel_manager: ChannelDataManager = ChannelDataManager(self, self.hass, self.config_entry)
        self._signals: dict[str, list[Callable]] = {}

        self._options_change_remove_callback = config_entry.add_update_listener(
            self._options_change_callback
        )

        self._controller_entity: ExtaLifeControllerType | None = None

        self._storage = {}

        self._is_unloading = False
        self._offline_check_cancel: Callable[[], None] | None = None

    # noinspection PyUnusedLocal
    async def _options_change_callback(self, hass: HomeAssistant, config_entry: ConfigEntry):
        """Options update listener"""

        await self.channel_manager.async_status_polling_task_setup(False)
        await self.channel_manager.async_version_polling_task_setup(False)

    async def platform_load(self, platform: str) -> bool:
        """Check if platform has been loaded if so will load awaiting channels and return true otherwise false"""

        if platform in self._platform_loader:
            _LOGGER.debug("Loading entities for %s", platform)
            await self._platform_loader[platform]()
            return True

        return False

    async def platform_register(self, platform: str, async_load_entities: Callable[[], Awaitable]) -> None:
        """registers platform loader for new entities and try to load all waiting channels"""

        _LOGGER.debug("Platform '%s' has been registered", platform)
        self._platform_loader.setdefault(platform, async_load_entities)
        await self.platform_load(platform)

    @staticmethod
    def _import_executor_callback(module: str, func: str) -> Callable[[HomeAssistant, ConfigEntry], Awaitable] | None:

        result = None
        package = ".".join(__package__.split(".")[:-1])  # 1 level above current package
        try:
            _LOGGER.debug("_import_executor_callback(), module: %s, from: %s", module, package)
            imp_module = importlib.import_module("." + module, package)

            _LOGGER.debug("_import_executor_callback(), func: %s", func)
            result = getattr(imp_module, func)
        except Exception as err:
            _LOGGER.warning("async_setup_custom_platforms(), failed to import module %s from package %s, %s",
                            module, package, repr(err))
        return result

    async def unload_entry_from_hass(self) -> bool:
        """Called when ConfigEntry is unloaded from Home Assistant"""
        self._is_unloading = True

        await Core._callbacks_cleanup(self.config_entry.entry_id)
        await self.channel_manager.async_status_polling_task_setup(False, False)
        await self.channel_manager.async_version_polling_task_setup(False, False)

        await self.api.async_disconnect()

        ir.async_delete_issue(self.hass, DOMAIN, self._offline_issue_id)
        self.channel_manager.async_remove_issues()

        result = True
        if self._platforms:
            result = await self.hass.config_entries.async_unload_platforms(
                self.config_entry, list(self._platforms)
            )

        await self.async_unload_custom_platforms()

        await self.unregister_controller()

        # remove instance only after everything is unloaded
        self._inst.pop(self.config_entry.entry_id, None)

        return result

    async def async_cleanup_failed_setup(self) -> None:
        """Release resources allocated during unsuccessful Config Entry setup"""
        self._is_unloading = True

        await Core._callbacks_cleanup(self.config_entry.entry_id)
        await self.channel_manager.async_status_polling_task_setup(False, False)
        await self.channel_manager.async_version_polling_task_setup(False, False)
        await self.api.async_disconnect()

        self._inst.pop(self.config_entry.entry_id, None)

    # noinspection PyUnusedLocal
    @classmethod
    async def _on_homeassistant_stop(cls, event) -> None:
        """Called when Home Assistant is shutting down"""
        cls._is_stopping = True

        for inst in list(cls._inst.values()):
            await Core._callbacks_cleanup(inst.config_entry.entry_id)
            await inst.channel_manager.async_status_polling_task_setup(False, False)
            await inst.channel_manager.async_version_polling_task_setup(False, False)

            await inst.api.async_disconnect()

    @classmethod
    async def _callbacks_cleanup(cls, entry_id: str | None = None) -> None:
        """Cleanup signal callbacks and time tracking callbacks"""
        instances = (
            [cls.get(entry_id)]
            if entry_id
            else list(cls._inst.values())
        )
        for inst in instances:
            if inst is None:
                continue
            inst.unregister_signal_callbacks()
            inst.unregister_track_time_callbacks()
            inst._offline_check_stop()

            if inst._options_change_remove_callback:
                with suppress(ValueError):
                    inst._options_change_remove_callback()
                inst._options_change_remove_callback = None

    @property
    def is_unloading(self) -> bool:
        """Config entry is being unloaded or Home Assistant is stopping"""
        return self._is_unloading or self._is_stopping

    async def _on_api_connect_callback(self) -> None:
        """Execute actions on (re)connection to controller"""

        if self.is_unloading:
            return

        # controller device must exist before devices discovered on it, which refer to it as their parent
        self._async_register_controller_device()

        # connection is back - controller is not offline anymore
        self._offline_check_stop()
        ir.async_delete_issue(self.hass, DOMAIN, self._offline_issue_id)
        self.async_signal_send(SIGNAL_CONTROLLER_STATE_UPDATED)

        await self.channel_manager.async_status_polling_task_setup()
        await self.channel_manager.async_version_polling_task_setup()

        # Update controller software info, but only on reconnect event
        # during first fire up, entity is still empty
        if self._controller_entity is not None:
            self._controller_entity.async_schedule_update_ha_state()

    async def _on_api_disconnect_callback(self) -> int:
        """Execute actions on disconnection with controller"""

        if self._is_unloading or self._is_stopping:
            return 0

        await self.channel_manager.async_status_polling_task_setup(False, False)
        await self.channel_manager.async_version_polling_task_setup(False, False)

        # Update controller software info
        if self._controller_entity is not None:
            self._controller_entity.async_schedule_update_ha_state()
        self.async_signal_send(SIGNAL_CONTROLLER_STATE_UPDATED)

        # raise repair issue if the controller won't be back in reasonable time
        self._offline_check_stop()
        self._offline_check_cancel = async_call_later(
            self.hass, CONTROLLER_OFFLINE_ISSUE_DELAY, self._async_offline_check
        )

        return 10

    @property
    def _offline_issue_id(self) -> str:
        return f"{ISSUE_CONTROLLER_OFFLINE}_{self.config_entry.entry_id}"

    def _offline_check_stop(self) -> None:
        if self._offline_check_cancel is not None:
            self._offline_check_cancel()
            self._offline_check_cancel = None

    # noinspection PyUnusedLocal
    async def _async_offline_check(self, now: datetime | None = None) -> None:
        """Called when controller is disconnected for a longer time"""
        self._offline_check_cancel = None
        if self.is_unloading or self.api.is_connected:
            return

        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._offline_issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_CONTROLLER_OFFLINE,
            translation_placeholders={
                "title": self.config_entry.title,
                "host": str(self.config_entry.data.get("controller_ip") or self.api.host),
                "minutes": str(CONTROLLER_OFFLINE_ISSUE_DELAY // 60),
            },
        )

    async def _on_api_notification_callback(self, notification: ExtaLifeResponse) -> None:
        if self._is_unloading or self._is_stopping:
            return

        notification_data = notification[0]
        notification_data.update({"command": notification.command})
        # forward only state notifications to data manager to update channels
        if notification.command == ExtaLifeCmd.CONTROL_DEVICE:
            self.channel_manager.channel_on_notify(notification_data)
        elif notification.command == ExtaLifeCmd.UPDATE_RECEIVERS:
            self.channel_manager.device_on_notify(notification_data)

        self._put_notification_on_event_bus(notification)

    async def unregister_controller(self) -> None:
        """Unregister controller from Device Registry"""
        if self._controller_entity:
            await self._controller_entity.unregister_controller()
        self._controller_entity = None

    async def register_controller(self) -> None:
        """Register controller in Device Registry and create its entity"""

        from .entities import ExtaLifeController

        await ExtaLifeController.register_controller(self.config_entry, self.api.serial_no)

    def _async_register_controller_device(self) -> None:
        """Create (or update) EFC-01 controller device in Device Registry"""
        from homeassistant.helpers import device_registry as dr
        from ..pyextalife import (
            PRODUCT_MANUFACTURER,
            ExtaLifeDeviceModelName,
        )

        if not self.api.mac:
            return

        serial_no = self.api.serial_no
        dr.async_get(self.hass).async_get_or_create(
            config_entry_id=self.config_entry.entry_id,
            identifiers={(DOMAIN, self.api.mac)},
            connections={(dr.CONNECTION_NETWORK_MAC, self.api.mac)},
            manufacturer=PRODUCT_MANUFACTURER,
            model=ExtaLifeDeviceModelName.EFC01,
            name=str(ExtaLifeDeviceModelName.EFC01),
            serial_number=f"{serial_no:06X} ({serial_no})",
            sw_version=self.api.version_installed or None,
        )

    def ver_check_required(self) -> bool:
        return self.api.ver_check_required()

    @property
    def ver_check_web(self) -> bool:
        return self._ver_check_web

    def ver_check_set(self, next_update: int, last_update: bool = False) -> bool:

        if next_update < 0:
            self._ver_check_web = False
        elif next_update > 0:
            self._ver_check_web = True
        if self.api.ver_check_set(next_update, last_update) and self._controller_entity is not None:
            self._controller_entity.async_schedule_update_ha_state()
            return True

        return False

    def controller_entity_added_to_hass(self, entity: ExtaLifeControllerType) -> None:
        """Callback called by controller entity when the entity is added to HA

        entity - ExtaLifeController object"""
        self._controller_entity = entity

    def _put_notification_on_event_bus(self, notification: ExtaLifeResponse) -> None:
        """ This method raises a notification on HA Event Bus """

        event = MAP_NOTIF_CMD_TO_EVENT.get(notification.command)
        if event:
            self._hass.bus.async_fire(event, event_data=notification[0])

    @property
    def api(self) -> ExtaLifeAPI:
        return self._api

    @property
    def channel_manager(self) -> ChannelDataManagerType:
        return self._channel_manager

    @property
    def config_entry(self) -> ConfigEntry:
        return self._config_entry

    @property
    def hass(self) -> HomeAssistant:
        return Core._hass

    @property
    def http_agent(self) -> str:

        return f"{self._config_entry.domain}/{self._integration.version} "\
               f"({homeassistant.const.APPLICATION_NAME}/{homeassistant.const.__version__})"

    @property
    def device_manager(self) -> DeviceManagerType:
        return self._device_manager

    @property
    def signal_remove_callbacks(self) -> dict[str, Callable]:
        return self._signal_callbacks

    def add_signal_remove_callback(self, callback: Callable, cb_type: str) -> None:
        self._signal_callbacks[cb_type] = callback

    def unregister_signal_callbacks(self) -> None:
        for _cb_type, callback in self.signal_remove_callbacks.items():
            callback()
        self._signal_callbacks = {}

    def unregister_track_time_callbacks(self) -> None:
        """Call delete callbacks for time interval registered callbacks"""
        for callback in self._track_time_callbacks:
            callback()

        self._track_time_callbacks = []

    def push_channels(self, platform: str, channels_data: list[dict[str, Any]], custom=False, append=False):
        """Store channel data temporarily for platform setup

        custom - custom, virtual platform"""
        if custom:
            if append:
                self._platforms_cust.setdefault(platform, [])
                for channel_data in channels_data:
                    self._platforms_cust[platform].append(channel_data)
            else:
                self._platforms_cust[platform] = channels_data
        else:
            if append:
                self._platforms.setdefault(platform, [])
                for channel_data in channels_data:
                    self._platforms[platform].append(channel_data)
            else:
                self._platforms[platform] = channels_data

    def get_channels(self, platform: str) -> list[dict[str, Any]]:
        """Return list of channel data per platform"""

        channels: list[dict[str, Any]] = self._platforms.get(platform)
        if channels is None:
            channels = self._platforms_cust.get(platform)
        return channels

    def pop_channels(self, platform: str) -> None:
        """Delete list of channel data per platform"""
        if self._platforms.get(platform) is None:
            self._platforms_cust[platform] = []
        else:
            self._platforms[platform] = []

    async def async_setup_custom_platform(self, platform: str):
        """Setup other, custom (pseudo)platforms"""

        async_setup_entry: Callable[[HomeAssistant, ConfigEntry], Awaitable] = \
            await self._hass.async_add_import_executor_job(self._import_executor_callback,
                                                           platform, "async_setup_entry")

        if async_setup_entry is not None:
            await async_setup_entry(self.hass, self.config_entry)
            _LOGGER.debug("Custom platform '%s' has been configured", platform)

    async def async_unload_custom_platforms(self) -> None:
        """Unload other, custom (pseudo)platforms"""

        for platform, _channels in self._platforms_cust.items():

            if platform.startswith("virtual"):
                # virtual platforms does not have import module so cannot be unloaded
                continue

            async_unload_entry: Callable[[HomeAssistant, ConfigEntry], Awaitable] = \
                await self._hass.async_add_import_executor_job(self._import_executor_callback,
                                                               platform, "async_unload_entry")
            if async_unload_entry is not None:
                await async_unload_entry(self.hass, self.config_entry)

    def storage_add(self, inst_id: str, inst_obj) -> None:
        self._storage.update({inst_id: inst_obj})

    def storage_get(self, inst_id: str) -> Any:
        return self._storage.get(inst_id)

    def storage_remove(self, inst_id: str) -> None:
        self._storage.pop(inst_id, None)

    def async_track_time_interval(
            self, callback: Callable[[datetime], Awaitable | None], interval: timedelta):
        """Add a listener that fires repetitively at every timedelta interval."""

        remove_callback = async_track_time_interval(self.hass, callback, interval)
        self._track_time_callbacks.append(remove_callback)

        def _managed_remove_callback() -> None:
            if remove_callback in self._track_time_callbacks:
                self._track_time_callbacks.remove(remove_callback)
                remove_callback()

        return _managed_remove_callback

    def signal_get_global_id(self, signal: str) -> str:
        """create global signal name uniq to entire HA"""

        return f"{self._config_entry.entry_id}-{signal}"

    def signal_has_targets(self, signal: str) -> bool:
        """Return True if anyone listens to the signal"""

        return bool(self._signals.get(self.signal_get_global_id(signal)))

    def async_signal_register(self, signal: str, target: Callable) -> Callable[[], None]:
        """Connect a callable function (sync or async) to a signal.

        This method must be run in the event loop.
        """
        signal_global: str = self.signal_get_global_id(signal)
        self._signals.setdefault(signal_global, []).append(target)

        _LOGGER.debug("async_signal_register(), signal: %s, target: %s", signal_global, target)

        def async_remove_signal() -> None:
            """Remove signal listener."""
            _LOGGER.debug("async_remove_signal(), signal: %s, target: %s", signal_global, target)
            try:
                self._signals[signal_global].remove(target)
            except (KeyError, ValueError):
                # KeyError is key target listener did not exist
                # ValueError if listener did not exist within signal
                _LOGGER.debug("Unable to remove unknown dispatcher %s", target)

        return async_remove_signal

    def async_signal_send(self, signal: str, *args: Any) -> None:
        """Send signal and data to every registered target.

        Synchronous targets are called immediately (keeps the order of notifications),
        coroutine targets are scheduled as tasks. An exception raised by one target
        does not prevent other targets from receiving the signal.
        This method must be run in the event loop.
        """
        signal_global: str = self.signal_get_global_id(signal)
        target_list = list(self._signals.get(signal_global, []))

        _LOGGER.debug("async_signal_send(), signal: %s, targets: %d, args: %s", signal_global, len(target_list), args)

        for target in target_list:
            try:
                result = target(*args)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Error while dispatching signal %s to %s", signal_global, target)
                continue

            if inspect.isawaitable(result):
                self._hass.async_create_task(result)

    def async_signal_send_sync(self, signal: str, args) -> None:
        """Send signal with single data argument. Kept for backward compatibility."""

        self.async_signal_send(signal, args)

    async def changelog_get(self) -> dict[str, Any]:
        """returns Zamel Changelog"""

        try:
            if self._changelog["next"] == 0 or datetime.now().timestamp() > self._changelog["next"]:
                session = async_get_clientsession(self.hass)
                headers: dict[str, str] = {
                    "Accept": "application/json",
                    "User-Agent": self.http_agent
                }
                async with asyncio.timeout(10):
                    async with session.get(URL_CHANGELOG_JSON, headers=headers) as response:
                        response.raise_for_status()
                        changelog = await response.json(content_type=None)
                self._changelog.update({"next": datetime.now().timestamp() + 6 * 3600, "data": changelog})

        except (TimeoutError, OSError) as conn_err:
            _LOGGER.warning("Failed to get changelog: %s", conn_err)
            self._changelog.update({"next": datetime.now().timestamp() + 60})

        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.warning("Failed to get changelog: %s", err)
            self._changelog.update({"next": datetime.now().timestamp() + 3600})

        return self._changelog["data"]

    async def i18n_get(
            self,
            category: str,
            key: str,
            placeholders: dict[str, str] | None = None,
    ) -> str:
        """Return a translated exception message.
        Defaults to English, requires translations to already be cached.
        """
        localize_key = f"component.{DOMAIN}.{category}.{key}"

        translations = await async_get_translations(self.hass, self.hass.config.language, category, [DOMAIN])
        if localize_key in translations:
            if message := translations[localize_key]:
                message = message.rstrip(".")
            if not placeholders:
                return message
            with suppress(KeyError):
                message = message.format(**placeholders)
            return message

        # We return the translation key when was not found in the cache
        return key

    async def async_logbook_write(self, entity: Entity, message_key, placeholder: dict[str, str]) -> None:
        name: str = f"{entity.device_entry.name} {entity.name}"
        message: str = await self.i18n_get("exceptions", f"logbook_{message_key}.message", placeholder)
        async_log_entry(self.hass, name, message, DOMAIN, entity.entity_id)

    async def async_i18n_get_notification_title(self, key: str, placeholder: dict[str, str]) -> str:
        return await self.i18n_get("exceptions", f"notification_{key}_title.message", placeholder)

    async def async_i18n_get_notification_message(self, key: str, placeholder: dict[str, str]) -> str:
        return await self.i18n_get("exceptions", f"notification_{key}_message.message", placeholder)

    def notification_push(self, message, title, notification_id: str = "") -> None:

        notification_id = f"{DOMAIN}.{notification_id}" if notification_id else None
        async_create_notification(self.hass, message, title, notification_id)
