"""Common fixtures for Exta Life tests."""
from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest

from .fake_controller import FakeController

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of custom integrations in all tests."""
    yield


@pytest.fixture(autouse=True)
def mock_logbook(hass):
    """Logbook depends on frontend & recorder which are not available in tests."""
    hass.config.components.add("logbook")


@pytest.fixture
async def controller() -> AsyncGenerator[FakeController, None]:
    """Running fake EFC-01 controller."""
    fake = FakeController()
    await fake.start()
    yield fake
    await fake.stop()
