"""Response time sensor, per-device 'responding' sensors and device diagnostics."""
from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.extalife.diagnostics import async_get_device_diagnostics
from custom_components.extalife.helpers.compat import async_get_device_by_identifier
from custom_components.extalife.helpers.const import DOMAIN

from .fake_controller import MAC, PASSWORD, FakeController
from .test_features import CONTROLLER_UNIQUE_ID
from .test_integration import SERIAL_DEAD, SERIAL_REMOTE, SERIAL_SOCKET, entity_id, setup_entry, unload_entry

CMD_CONTROL_DEVICE = 20


async def test_response_time_sensor(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller)
    response_time = entity_id(hass, "sensor", f"{CONTROLLER_UNIQUE_ID}-response_time")
    socket = entity_id(hass, "switch", f"extalife-{SERIAL_SOCKET}-11-1")

    # no control command yet
    assert hass.states.get(response_time).state == STATE_UNKNOWN

    controller.response_delay[CMD_CONTROL_DEVICE] = 0.3
    await hass.services.async_call("switch", "turn_on", {"entity_id": socket}, blocking=True)

    state = hass.states.get(response_time)
    assert 0.3 <= float(state.state) < 1.5
    assert state.attributes["commands"] == 1
    assert state.attributes["failed_commands"] == 0
    assert state.attributes["last_failed"] is False
    assert state.attributes["all_commands"] > 1  # login, config, polling...

    await unload_entry(hass, entry)


async def test_responding_sensors(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller)

    socket_responding = entity_id(hass, "binary_sensor", f"extalife-{SERIAL_SOCKET}-11-1-responding")
    dead_responding = entity_id(hass, "binary_sensor", f"extalife-{SERIAL_DEAD}-15-1-responding")
    dead_switch = entity_id(hass, "switch", f"extalife-{SERIAL_DEAD}-15-1")

    assert hass.states.get(socket_responding).state == STATE_ON
    assert hass.states.get(socket_responding).attributes["friendly_name"] == "ROP-21 Socket responding"
    # the switch itself is unavailable, the diagnostic sensor stays available and reports the problem
    assert hass.states.get(dead_switch).state == STATE_UNAVAILABLE
    assert hass.states.get(dead_responding).state == STATE_OFF

    # device is back - next status poll reports it
    controller.receivers[2]["state"][0]["is_timeout"] = False
    controller_entity = entity_id(hass, DOMAIN, f"extalife-{int(MAC[6:], 16)}-conn")
    await hass.services.async_call(DOMAIN, "refresh_state", {"entity_id": controller_entity}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(dead_responding).state == STATE_ON
    assert hass.states.get(dead_switch).state == STATE_OFF

    # transmitters do not report timeouts - no sensor
    assert er_get(hass, "binary_sensor", f"extalife-{SERIAL_REMOTE}-30-#-responding") is None

    await unload_entry(hass, entry)


def er_get(hass: HomeAssistant, platform: str, unique_id: str) -> str | None:
    from homeassistant.helpers import entity_registry as er
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)


async def test_device_diagnostics(hass: HomeAssistant, controller: FakeController) -> None:
    entry: MockConfigEntry = await setup_entry(hass, controller)

    device = async_get_device_by_identifier(hass, (DOMAIN, str(SERIAL_SOCKET)), entry.entry_id)
    diagnostics = await async_get_device_diagnostics(hass, entry, device)
    assert diagnostics["device"]["model"] == "ROP-21"
    assert diagnostics["channels"]["11-1"]["alias"] == "Socket"
    assert diagnostics["channels"]["11-1"]["type"] == 10
    assert "11" in diagnostics["device_config"]
    assert PASSWORD not in str(diagnostics)

    mac = ":".join(MAC.lower()[i:i + 2] for i in range(0, 12, 2))
    controller_device = async_get_device_by_identifier(hass, (DOMAIN, mac), entry.entry_id)
    diagnostics = await async_get_device_diagnostics(hass, entry, controller_device)
    assert diagnostics["controller"]["connected"] is True
    assert diagnostics["controller"]["version_installed"] == "1.6.30"
    assert "all_commands" in diagnostics["controller"]

    await unload_entry(hass, entry)
