"""Integration tests for Exta Life running against a fake EFC-01 controller."""
from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from typing import Any
from unittest.mock import patch

from homeassistant.components import automation
from homeassistant.components.device_automation import DeviceAutomationType
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    async_get_device_automations,
)

from custom_components.extalife.helpers.compat import async_get_device_by_identifier
from custom_components.extalife.diagnostics import async_get_config_entry_diagnostics
from custom_components.extalife.helpers.const import DOMAIN
from custom_components.extalife.helpers.core import Core
from custom_components.extalife.pyextalife import ExtaLifeAPI

from .fake_controller import MAC, PASSWORD, USERNAME, FakeController

SERIAL_SOCKET = 0x0B0001
SERIAL_LAMP = 0x0B0004
SERIAL_DEAD = 0x0B0005
SERIAL_BLIND = 0x0C0002
SERIAL_METER = 0x230003
SERIAL_TEMP = 0x140020
SERIAL_REMOTE = 0x060030


async def setup_entry(hass: HomeAssistant, controller: FakeController,
                      options: dict[str, Any] | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="EFC-01 Test",
        unique_id="aa:bb:cc:11:22:33",
        data={"controller_ip": controller.address, "user": USERNAME, "password": PASSWORD, "recv_timeout": 5},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def unload_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


def entity_id(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    result = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert result is not None, f"{platform} entity with unique_id {unique_id} not found"
    return result


async def wait_for(hass: HomeAssistant, condition, timeout: float = 3.0) -> None:
    """Wait (real time) until condition is met - data travels through real TCP socket"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await hass.async_block_till_done()
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met in time")


async def test_setup_creates_entities(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller)

    socket = entity_id(hass, "switch", f"extalife-{SERIAL_SOCKET}-11-1")
    assert hass.states.get(socket).state == STATE_OFF

    lamp = entity_id(hass, "light", f"extalife-{SERIAL_LAMP}-14-1")
    assert hass.states.get(lamp).state == STATE_ON

    blind = entity_id(hass, "cover", f"extalife-{SERIAL_BLIND}-12-1")
    state = hass.states.get(blind)
    assert state.state == "closed"
    assert state.attributes["current_position"] == 0

    temp = entity_id(hass, "sensor", f"extalife-{SERIAL_TEMP}-20-1")
    assert float(hass.states.get(temp).state) == 21.5

    # not responding device is unavailable (option 'disable_not_responding' is on by default)
    dead = entity_id(hass, "switch", f"extalife-{SERIAL_DEAD}-15-1")
    assert hass.states.get(dead).state == STATE_UNAVAILABLE

    # MEM-21: every phase gets its own sensors even if phases have identical values
    voltages = [entity_id(hass, "sensor", f"extalife-{SERIAL_METER}-13-1-phase[{phase}].voltage")
                for phase in range(3)]
    assert len(set(voltages)) == 3
    assert float(hass.states.get(voltages[0]).state) == 230.0

    energy = entity_id(hass, "sensor", f"extalife-{SERIAL_METER}-13-1")
    assert float(hass.states.get(energy).state) == 12345.0

    await unload_entry(hass, entry)


async def test_not_responding_option_off(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller, options={"general": {"disable_not_responding": False}})

    dead = entity_id(hass, "switch", f"extalife-{SERIAL_DEAD}-15-1")
    assert hass.states.get(dead).state == STATE_OFF

    await unload_entry(hass, entry)


async def test_notifications_and_unknown_messages(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller)
    socket = entity_id(hass, "switch", f"extalife-{SERIAL_SOCKET}-11-1")

    controller.notify(20, {"id": 11, "channel": 1, "state": 1})
    await wait_for(hass, lambda: hass.states.get(socket).state == STATE_ON)

    # unknown command, unknown status and garbage must not break the connection
    controller.send({"command": 9999, "status": "notification", "data": {}})
    controller.send({"command": 20, "status": "something-new", "data": {}})
    controller.send_raw(b"this is not json")

    controller.notify(20, {"id": 11, "channel": 1, "state": 0})
    await wait_for(hass, lambda: hass.states.get(socket).state == STATE_OFF)
    assert controller.connections == 1

    await unload_entry(hass, entry)


async def test_switch_control(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller)
    socket = entity_id(hass, "switch", f"extalife-{SERIAL_SOCKET}-11-1")

    await hass.services.async_call("switch", "turn_on", {"entity_id": socket}, blocking=True)
    assert hass.states.get(socket).state == STATE_ON
    assert {"id": 11, "channel": 1, "state": 1} == controller.received[-1]["data"]

    blind = entity_id(hass, "cover", f"extalife-{SERIAL_BLIND}-12-1")
    await hass.services.async_call("cover", "open_cover", {"entity_id": blind}, blocking=True)
    assert controller.received[-1]["data"]["value"] == 0
    assert hass.states.get(blind).state == "open"

    await unload_entry(hass, entry)


async def test_inverted_cover_control_is_consistent(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller, options={"cover": {"inverted_control": True}})
    blind = entity_id(hass, "cover", f"extalife-{SERIAL_BLIND}-12-1")

    # inverted: value 100 means fully open
    state = hass.states.get(blind)
    assert state.attributes["current_position"] == 100
    assert state.state == "open"

    await hass.services.async_call("cover", "close_cover", {"entity_id": blind}, blocking=True)
    assert controller.received[-1]["data"]["value"] == 0
    assert hass.states.get(blind).state == "closed"

    await unload_entry(hass, entry)


async def _click(hass: HomeAssistant, controller: FakeController, data: dict[str, Any]) -> None:
    controller.notify(20, {**data, "state": 1})
    controller.notify(20, {**data, "state": 0})
    await asyncio.sleep(0.2)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
    await hass.async_block_till_done()


async def test_transmitter_events(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller)
    events = async_capture_events(hass, "extalife_transmitter")

    await _click(hass, controller, {"id": 30, "button": 1})
    assert [event.data["type"] for event in events] == ["button_down", "button_up", "button_single_click"]
    assert events[0].data["subtype"] == "button_1"

    # second gesture on the same button must work as well
    events.clear()
    await _click(hass, controller, {"id": 30, "button": 1, "channel": 1})
    assert [event.data["type"] for event in events] == ["button_down", "button_up", "button_single_click"]

    await unload_entry(hass, entry)


async def test_device_trigger_automation(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller)

    device = async_get_device_by_identifier(hass, (DOMAIN, SERIAL_REMOTE), entry.entry_id)
    assert device is not None

    triggers = await async_get_device_automations(hass, DeviceAutomationType.TRIGGER, device.id)
    assert len(triggers) == 4 * 6  # P-457/4: 4 buttons x 6 trigger types

    calls = async_capture_events(hass, "extalife_test_fired")
    assert await async_setup_component(hass, automation.DOMAIN, {
        automation.DOMAIN: [{
            "trigger": {
                "platform": "device", "domain": DOMAIN, "device_id": device.id,
                "type": "button_double_click", "subtype": "button_2",
            },
            "action": {"event": "extalife_test_fired"},
        }]
    })
    await hass.async_block_till_done()

    controller.notify(20, {"id": 30, "button": 2, "state": 1})
    controller.notify(20, {"id": 30, "button": 2, "state": 0})
    controller.notify(20, {"id": 30, "button": 2, "state": 1})
    controller.notify(20, {"id": 30, "button": 2, "state": 0})
    await asyncio.sleep(0.2)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
    await hass.async_block_till_done()

    assert len(calls) == 1

    await unload_entry(hass, entry)


async def test_diagnostics_redacts_credentials(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert PASSWORD not in str(diagnostics)
    assert "external_ip" not in diagnostics
    assert diagnostics["entry"]["data"]["password"] == "**REDACTED**"

    await unload_entry(hass, entry)


async def test_large_message(hass: HomeAssistant, controller: FakeController) -> None:
    # more than default StreamReader limit (64 KiB)
    controller.receivers[0]["description"] = "x" * 200_000
    entry = await setup_entry(hass, controller)

    entity_id(hass, "switch", f"extalife-{SERIAL_SOCKET}-11-1")
    assert controller.connections == 1

    await unload_entry(hass, entry)


async def test_reconnect_after_connection_loss(hass: HomeAssistant, controller: FakeController) -> None:
    original = Core._on_api_disconnect_callback

    async def fast_reconnect(self: Core) -> int:
        result = await original(self)
        return 0.1 if result else 0

    with patch.object(Core, "_on_api_disconnect_callback", fast_reconnect):
        entry = await setup_entry(hass, controller)
        core: Core = Core.get(entry.entry_id)
        socket = entity_id(hass, "switch", f"extalife-{SERIAL_SOCKET}-11-1")

        controller.drop_connections()
        await wait_for(hass, lambda: controller.connections == 2 and core.api.is_connected, timeout=5)
        # wait until state refresh done after reconnection is finished (periodic version poll is set up last)
        await wait_for(hass, lambda: core.channel_manager._version_polling_task_stop is not None, timeout=5)

        controller.notify(20, {"id": 11, "channel": 1, "state": 1})
        await wait_for(hass, lambda: hass.states.get(socket).state == STATE_ON)

        await unload_entry(hass, entry)


async def test_command_timeout(hass: HomeAssistant, controller: FakeController) -> None:
    api = ExtaLifeAPI(hass.loop)
    await api.async_connect(USERNAME, PASSWORD, "127.0.0.1", controller.port, conn_timeout=2, recv_timeout=1)
    assert api.is_connected
    assert api.mac == ":".join(MAC.lower()[i:i + 2] for i in range(0, 12, 2))

    controller.ignored_commands.add(27)
    start = time.monotonic()
    assert await api.async_get_dev_config_details(11) is None
    elapsed = time.monotonic() - start

    # timeout is the configured one, not doubled
    assert 0.9 < elapsed < 1.6
    assert not api.is_connected

    await api.async_disconnect()


async def test_unload_and_reload(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    socket = entity_id(hass, "switch", f"extalife-{SERIAL_SOCKET}-11-1")
    assert hass.states.get(socket).state == STATE_OFF

    await unload_entry(hass, entry)


async def test_setup_retry_when_controller_unreachable(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, version=2, title="EFC-01",
        data={"controller_ip": "127.0.0.1:1", "user": USERNAME, "password": PASSWORD, "recv_timeout": 5},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert Core.get(entry.entry_id) is None


async def test_migration_from_version_1(hass: HomeAssistant, controller: FakeController) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, version=1, title="EFC-01",
        data={"controller_ip": controller.address, "user": USERNAME, "password": PASSWORD,
              "recv_timeout": 5, "poll_interval": 7},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 2
    assert "poll_interval" not in entry.data
    assert entry.options["general"]["poll_interval"] == 7

    await unload_entry(hass, entry)
