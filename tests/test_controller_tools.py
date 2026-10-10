"""Record traffic button, last status update sensor and firmware version check scheduling."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.extalife.helpers.const import DOMAIN
from custom_components.extalife.helpers.core import Core

from .fake_controller import MAC, FakeController
from .test_features import CONTROLLER_UNIQUE_ID
from .test_integration import entity_id, setup_entry, unload_entry, wait_for

CMD_CHECK_VERSION = 151


def _web_version_checks(controller: FakeController) -> int:
    return len([r for r in controller.received
                if r["command"] == CMD_CHECK_VERSION and (r.get("data") or {}).get("check_web_version")])


async def test_record_traffic_button(hass: HomeAssistant, controller: FakeController, tmp_path: Path) -> None:
    hass.config.config_dir = str(tmp_path)
    entry = await setup_entry(hass, controller)
    core: Core = Core.get(entry.entry_id)
    button = entity_id(hass, "button", f"{CONTROLLER_UNIQUE_ID}-record_traffic")
    assert hass.states.get(button).attributes["friendly_name"] == "EFC-01 Record traffic (10 min)"

    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    assert core.is_recording

    # second press stops the recording and saves it
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    assert not core.is_recording
    assert len(list((tmp_path / DOMAIN / "recordings").glob("traffic_*.jsonl"))) == 1

    await unload_entry(hass, entry)


async def test_last_status_update_sensor(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller)
    sensor = entity_id(hass, "sensor", f"{CONTROLLER_UNIQUE_ID}-last_status_update")

    first = hass.states.get(sensor).state
    assert first != STATE_UNKNOWN
    assert dt_util.utcnow() - dt_util.parse_datetime(first) < timedelta(minutes=1)

    await asyncio.sleep(0.05)
    controller_entity = entity_id(hass, DOMAIN, f"extalife-{int(MAC[6:], 16)}-conn")
    await hass.services.async_call(DOMAIN, "refresh_state", {"entity_id": controller_entity}, blocking=True)
    await hass.async_block_till_done()
    assert dt_util.parse_datetime(hass.states.get(sensor).state) >= dt_util.parse_datetime(first)

    await unload_entry(hass, entry)


async def test_version_check_scheduled(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller)
    core: Core = Core.get(entry.entry_id)

    # on connection only the local version is read, the internet check is scheduled for later
    assert _web_version_checks(controller) == 0
    assert core.channel_manager._version_polling_task_stop is not None
    assert not core.api.ver_check_required()

    # check becomes due - the next tick of the version poll task performs it with the web check
    core.api.ver_check_set(1)
    await asyncio.sleep(1.1)
    assert core.api.ver_check_required()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=11))
    await wait_for(hass, lambda: _web_version_checks(controller) == 1)
    # next check is in 12 hours (default), so the following tick does nothing
    await wait_for(hass, lambda: not core.api.ver_check_required())
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=22))
    await hass.async_block_till_done()
    await asyncio.sleep(0.2)
    assert _web_version_checks(controller) == 1

    await unload_entry(hass, entry)


async def test_version_check_disabled(hass: HomeAssistant, controller: FakeController) -> None:
    entry = await setup_entry(hass, controller, options={"general": {"version_interval": 0}})
    core: Core = Core.get(entry.entry_id)

    assert core.channel_manager._version_polling_task_stop is None
    assert not core.api.ver_check_required()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=11))
    await hass.async_block_till_done()
    await asyncio.sleep(0.2)
    assert _web_version_checks(controller) == 0

    # the manual check (button) still works and does not enable the schedule
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id(hass, "button", f"{CONTROLLER_UNIQUE_ID}-update")}, blocking=True
    )
    assert core.channel_manager._version_polling_task_stop is None
    assert not core.api.ver_check_required()

    await unload_entry(hass, entry)
