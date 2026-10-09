"""Tests for Exta Life config & options flow."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.extalife.helpers.const import DOMAIN

from .fake_controller import PASSWORD, USERNAME, FakeController


async def test_user_flow(hass: HomeAssistant, controller: FakeController) -> None:
    with patch("custom_components.extalife.config_flow.ExtaLifeAPI.discover_controller", return_value=""):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "confirm"

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "init"

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {
            "controller_ip": controller.address, "recv_timeout": 5, "user": USERNAME, "password": "wrong",
        })
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "extalife_invalid_cred"}

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {
            "controller_ip": controller.address, "recv_timeout": 5, "user": USERNAME, "password": PASSWORD,
        })
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "title"

    with patch("custom_components.extalife.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"title": "Home"})
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home"
    assert result["data"]["password"] == PASSWORD
    assert result["result"].unique_id == "aa:bb:cc:11:22:33"


async def test_options_flow(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, version=2, data={"controller_ip": "127.0.0.1"}, options={})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "general"

    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "poll_interval": 9, "version_interval": 24, "disable_not_responding": False,
    })
    assert result["step_id"] == "light"

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"icons_list": [13]})
    assert result["step_id"] == "cover"

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"inverted_control": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY

    assert entry.options["general"]["poll_interval"] == 9
    assert entry.options["general"]["disable_not_responding"] is False
    assert entry.options["light"]["icons_list"] == [13]
    assert entry.options["cover"]["inverted_control"] is True
