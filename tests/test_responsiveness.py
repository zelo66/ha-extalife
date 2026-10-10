"""Responsiveness of device control while the controller is busy or slow."""
from __future__ import annotations

import asyncio
import time

import pytest
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.extalife.helpers.const import DOMAIN
from custom_components.extalife.helpers.core import Core

from .fake_controller import PASSWORD, USERNAME, FakeController
from .test_integration import SERIAL_SOCKET, entity_id, setup_entry, unload_entry, wait_for

CMD_CONTROL_DEVICE = 20
CMD_FETCH_RECEIVER_CONFIG_DETAILS = 27
CMD_FETCH_RECEIVERS = 37


async def test_control_is_not_queued_behind_polling(hass: HomeAssistant, controller: FakeController) -> None:
    """Switching a light must not wait until the whole background polling of all devices is finished"""
    entry = await setup_entry(hass, controller)
    core: Core = Core.get(entry.entry_id)
    socket = entity_id(hass, "switch", f"extalife-{SERIAL_SOCKET}-11-1")

    # every device takes 0.5 s to answer configuration request - polling of all devices takes ~3.5 seconds
    controller.response_delay[CMD_FETCH_RECEIVER_CONFIG_DETAILS] = 0.5
    polling = hass.async_create_task(core.channel_manager.async_version_polling_task_run())
    await asyncio.sleep(0.1)

    start = time.monotonic()
    await hass.services.async_call("switch", "turn_on", {"entity_id": socket}, blocking=True)
    elapsed = time.monotonic() - start

    # at most the one request being processed by the controller is waited for (0.5 s + overhead),
    # not the whole polling of all devices
    assert elapsed < 1.5, f"switching took {elapsed:.2f} s"
    assert hass.states.get(socket).state == STATE_ON

    await polling
    await unload_entry(hass, entry)


async def test_state_is_updated_before_controller_confirms(hass: HomeAssistant,
                                                           controller: FakeController) -> None:
    """UI shows the requested state immediately, not after the radio round trip"""
    entry = await setup_entry(hass, controller)
    socket = entity_id(hass, "switch", f"extalife-{SERIAL_SOCKET}-11-1")
    lamp = entity_id(hass, "light", "extalife-720900-14-1")

    controller.response_delay[CMD_CONTROL_DEVICE] = 1.0
    task = hass.async_create_task(
        hass.services.async_call("switch", "turn_on", {"entity_id": socket}, blocking=True)
    )
    await asyncio.sleep(0.3)
    assert hass.states.get(socket).state == STATE_ON
    await task

    # quick off & on of a light
    await hass.services.async_call("light", "turn_off", {"entity_id": lamp}, blocking=False)
    await hass.services.async_call("light", "turn_on", {"entity_id": lamp}, blocking=False)
    await asyncio.sleep(0.3)
    assert hass.states.get(lamp).state == STATE_ON
    await wait_for(hass, lambda: len([r for r in controller.received if r["command"] == CMD_CONTROL_DEVICE]) == 3,
                   timeout=5)
    # commands reached the controller in the order they were issued
    assert [r["data"]["state"] for r in controller.received if r["command"] == CMD_CONTROL_DEVICE] == [1, 0, 1]

    await unload_entry(hass, entry)


async def test_failed_command_reverts_state(hass: HomeAssistant, controller: FakeController) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, version=2, title="EFC-01",
        data={"controller_ip": controller.address, "user": USERNAME, "password": PASSWORD, "recv_timeout": 1},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    core: Core = Core.get(entry.entry_id)
    socket = entity_id(hass, "switch", f"extalife-{SERIAL_SOCKET}-11-1")

    controller.ignored_commands.add(CMD_CONTROL_DEVICE)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("switch", "turn_on", {"entity_id": socket}, blocking=True)

    assert hass.states.get(socket).state == STATE_OFF
    # a single lost answer does not drop the connection to the controller
    assert core.api.is_connected
    assert controller.connections == 1

    controller.ignored_commands.clear()
    await hass.services.async_call("switch", "turn_on", {"entity_id": socket}, blocking=True)
    assert hass.states.get(socket).state == STATE_ON

    await unload_entry(hass, entry)


async def test_polling_does_not_revert_pending_command(hass: HomeAssistant, controller: FakeController) -> None:
    """Device state snapshot taken by the controller before a command must not flip the UI back"""
    entry = await setup_entry(hass, controller)
    core: Core = Core.get(entry.entry_id)
    socket = entity_id(hass, "switch", f"extalife-{SERIAL_SOCKET}-11-1")
    states = async_capture_events(hass, "state_changed")

    # status polling is in progress (controller answers slowly) when user switches the socket on
    controller.response_delay[CMD_FETCH_RECEIVERS] = 0.5
    polling = hass.async_create_task(core.channel_manager.async_status_polling_task_setup())
    await asyncio.sleep(0.1)
    await hass.services.async_call("switch", "turn_on", {"entity_id": socket}, blocking=True)
    await polling
    await hass.async_block_till_done()

    socket_states = [e.data["new_state"].state for e in states if e.data["entity_id"] == socket]
    assert STATE_OFF not in socket_states, socket_states
    assert hass.states.get(socket).state == STATE_ON

    await unload_entry(hass, entry)
