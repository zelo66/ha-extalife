"""Tests for event entities, controller diagnostic entities, naming and repair issues."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.extalife.helpers.compat import async_get_device_by_identifier
from custom_components.extalife.helpers.const import DOMAIN

from .fake_controller import MAC, FakeController
from .test_integration import (
    SERIAL_METER,
    SERIAL_REMOTE,
    SERIAL_SOCKET,
    _click,
    entity_id,
    setup_entry,
    unload_entry,
    wait_for,
)

SERIAL_CONTROLLER = int(MAC[6:], 16)
CONTROLLER_UNIQUE_ID = f"extalife-{SERIAL_CONTROLLER}-99"


async def test_transmitter_button_event_entities(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller)

    # P-457/4 has 4 buttons
    buttons = [entity_id(hass, "event", f"extalife-{SERIAL_REMOTE}-30-#-button_{n}") for n in range(1, 5)]
    assert hass.states.get(buttons[0]).state == STATE_UNKNOWN
    assert hass.states.get(buttons[0]).attributes["friendly_name"] == "P-457/4 Button 1"

    await _click(hass, controller, {"id": 30, "button": 2})

    state = hass.states.get(buttons[1])
    assert state.state != STATE_UNKNOWN
    assert state.attributes["event_type"] == "button_single_click"
    # other buttons are not affected
    assert hass.states.get(buttons[0]).state == STATE_UNKNOWN

    await unload_entry(hass, entry)


async def test_scene_event_entity(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller)
    scene = entity_id(hass, "event", f"{CONTROLLER_UNIQUE_ID}-scene")

    controller.notify(44, {"id": 7, "name": "Evening"})
    await wait_for(hass, lambda: hass.states.get(scene).state != STATE_UNKNOWN)

    state = hass.states.get(scene)
    assert state.attributes["event_type"] == "scene_activated"
    assert state.attributes["id"] == 7

    await unload_entry(hass, entry)


async def test_controller_diagnostic_entities(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller)

    connection = entity_id(hass, "binary_sensor", f"{CONTROLLER_UNIQUE_ID}-connectivity")
    ip_address = entity_id(hass, "sensor", f"{CONTROLLER_UNIQUE_ID}-ip_address")
    assert hass.states.get(connection).state == STATE_ON
    assert hass.states.get(ip_address).state == "127.0.0.1"

    # controller disappears - the integration retries, connectivity goes off
    await controller.stop()
    await wait_for(hass, lambda: hass.states.get(connection).state == STATE_OFF)

    await unload_entry(hass, entry)


async def test_device_and_sensor_names(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller)

    device = async_get_device_by_identifier(hass, (DOMAIN, str(SERIAL_SOCKET)), entry.entry_id)
    assert device is not None
    assert device.name == "ROP-21"
    assert device.manufacturer == "ZAMEL"

    socket = entity_id(hass, "switch", f"extalife-{SERIAL_SOCKET}-11-1")
    assert socket == "switch.rop_21_socket"

    voltage = entity_id(hass, "sensor", f"extalife-{SERIAL_METER}-13-1-phase[0].voltage")
    assert hass.states.get(voltage).attributes["friendly_name"] == "MEM-21 Meter L1 voltage"

    controller_device = async_get_device_by_identifier(
        hass, (DOMAIN, ":".join(MAC.lower()[i:i + 2] for i in range(0, 12, 2))), entry.entry_id
    )
    assert controller_device is not None
    assert device.via_device_id == controller_device.id

    await unload_entry(hass, entry)


async def test_unsupported_devices_issue(hass: HomeAssistant, controller: FakeController) -> None:
    controller.receivers.append({   # GKN-01 is not supported (yet)
        "id": 40, "type": 14, "serial": 0x0E0040,
        "state": [{"alias": "Heating", "channel": 1, "is_timeout": False}],
    })
    entry = await setup_entry(hass, controller)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"unsupported_devices_{entry.entry_id}")
    assert issue is not None
    assert issue.translation_placeholders["devices"] == "GKN-01"

    await unload_entry(hass, entry)
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"unsupported_devices_{entry.entry_id}") is None


async def test_no_unsupported_devices_issue(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller)
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"unsupported_devices_{entry.entry_id}") is None
    await unload_entry(hass, entry)


async def test_controller_offline_issue(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller)
    issue_id = f"controller_offline_{entry.entry_id}"

    await controller.stop()
    connection = entity_id(hass, "binary_sensor", f"{CONTROLLER_UNIQUE_ID}-connectivity")
    await wait_for(hass, lambda: hass.states.get(connection).state == STATE_OFF)

    # short outage - no issue
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=5))
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=16))
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.ERROR

    await unload_entry(hass, entry)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
