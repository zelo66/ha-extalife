"""Traffic recording (extalife.record_traffic) and replay of recordings made on real controllers.

Every *.jsonl file placed in tests/recordings is replayed against the integration: the integration must set up,
create entities and process all recorded notifications without errors.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.extalife.helpers.const import DOMAIN
from custom_components.extalife.helpers.recorder import REDACTED, load_recording, redact

from .fake_controller import PASSWORD, USERNAME, FakeController
from .test_integration import (
    SERIAL_REMOTE,
    SERIAL_SOCKET,
    _click,
    entity_id,
    setup_entry,
    unload_entry,
    wait_for,
)

RECORDINGS_DIR = Path(__file__).parent / "recordings"
RECORDINGS = sorted(RECORDINGS_DIR.glob("*.jsonl"))


async def _wait_click(hass: HomeAssistant) -> None:
    """Let the gesture detection window of transmitter events expire"""
    await asyncio.sleep(0.2)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
    await hass.async_block_till_done()


async def _record(hass: HomeAssistant, controller: FakeController, tmp_path: Path) -> Path:
    """Record traffic of a fake controller session using the service, return the recording file"""
    hass.config.config_dir = str(tmp_path)
    entry = await setup_entry(hass, controller)
    controller_entity = entity_id(hass, DOMAIN, f"extalife-{int('112233', 16)}-conn")

    await hass.services.async_call(DOMAIN, "record_traffic", {"entity_id": controller_entity, "duration": 5},
                                   blocking=True)
    with pytest.raises(HomeAssistantError):
        # only one recording at a time
        await hass.services.async_call(DOMAIN, "record_traffic", {"entity_id": controller_entity, "duration": 5},
                                       blocking=True)

    socket = entity_id(hass, "switch", f"extalife-{SERIAL_SOCKET}-11-1")
    controller.notify(20, {"id": 11, "channel": 1, "state": 1})
    await wait_for(hass, lambda: hass.states.get(socket).state == STATE_ON)
    await _click(hass, controller, {"id": 30, "button": 1})
    controller.send_raw(b"garbage from controller")
    controller.notify(20, {"id": 11, "channel": 1, "state": 0})
    await wait_for(hass, lambda: hass.states.get(socket).state == STATE_OFF)

    await hass.services.async_call(DOMAIN, "record_traffic", {"entity_id": controller_entity, "duration": 0},
                                   blocking=True)
    await unload_entry(hass, entry)

    files = list((tmp_path / DOMAIN / "recordings").glob("traffic_*.jsonl"))
    assert len(files) == 1
    return files[0]


async def test_record_traffic(hass: HomeAssistant, controller: FakeController, tmp_path: Path) -> None:
    recording = await _record(hass, controller, tmp_path)

    content = recording.read_text(encoding="utf-8")
    assert PASSWORD not in content
    assert USERNAME not in content

    header, records = load_recording(recording)
    assert header["messages"] == len(records)
    assert header["controller_version"] == "1.6.30"

    # snapshot of the controller and devices taken when recording started
    commands = {r["msg"]["command"] for r in records if r["dir"] == "in" and "msg" in r}
    assert {154, 151, 37, 38, 39} <= commands
    # notifications and invalid messages are recorded as well
    assert any(r.get("msg", {}).get("status") == "notification" for r in records)
    assert any(r.get("raw") == "garbage from controller" for r in records)



def test_redact() -> None:
    data = {"login": "root", "password": "x", "devices": [{"alias": "Kitchen", "user": "a", "Password": "y"}]}
    assert redact(data) == {
        "login": REDACTED, "password": REDACTED,
        "devices": [{"alias": "Kitchen", "user": REDACTED, "Password": REDACTED}],
    }


async def test_replay_recording(hass: HomeAssistant, controller: FakeController, tmp_path: Path) -> None:
    recording = await _record(hass, controller, tmp_path)
    entities_before = {
        entry.unique_id for entry in er.async_get(hass).entities.values() if entry.platform == DOMAIN
    }

    replay = FakeController()
    replay.load_recording(recording)
    await replay.start()
    try:
        entry = MockConfigEntry(
            domain=DOMAIN, version=2, title="Replay",
            data={"controller_ip": replay.address, "user": "any", "password": "any", "recv_timeout": 5},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED

        entities_after = {
            e.unique_id for e in er.async_get(hass).entities.values()
            if e.platform == DOMAIN and e.config_entry_id == entry.entry_id
        }
        # recording contains the controller and all devices - the same entities are created
        assert entities_before == entities_after

        socket = entity_id(hass, "switch", f"extalife-{SERIAL_SOCKET}-11-1")
        switch_states = async_capture_events(hass, "state_changed")
        assert replay.send_recorded_notifications() > 0

        # recorded switch on / off notifications are replayed
        await wait_for(hass, lambda: [
            e.data["new_state"].state for e in switch_states if e.data["entity_id"] == socket
        ] == [STATE_ON, STATE_OFF])
        # recorded remote click is replayed
        button = entity_id(hass, "event", f"extalife-{SERIAL_REMOTE}-30-#-button_1")
        await _wait_click(hass)
        assert hass.states.get(button).attributes["event_type"] == "button_single_click"

        await unload_entry(hass, entry)
    finally:
        await replay.stop()


@pytest.mark.parametrize("recording", RECORDINGS, ids=[path.stem for path in RECORDINGS])
async def test_real_controller_recording(hass: HomeAssistant, recording: Path,
                                         caplog: pytest.LogCaptureFixture) -> None:
    """Recordings made on real installations must be processed without errors"""
    replay = FakeController()
    replay.load_recording(recording)
    await replay.start()
    try:
        entry = MockConfigEntry(
            domain=DOMAIN, version=2, title=recording.stem,
            data={"controller_ip": replay.address, "user": "any", "password": "any", "recv_timeout": 5},
        )
        entry.add_to_hass(hass)
        with caplog.at_level(logging.WARNING, logger="custom_components.extalife"):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            assert entry.state is ConfigEntryState.LOADED

            replay.send_recorded_notifications()
            await wait_for(hass, lambda: True)
            await _wait_click(hass)

        errors = [r for r in caplog.records
                  if r.name.startswith("custom_components.extalife") and r.levelno >= logging.ERROR]
        assert not errors, json.dumps([r.getMessage() for r in errors], indent=1)

        await unload_entry(hass, entry)
    finally:
        await replay.stop()
