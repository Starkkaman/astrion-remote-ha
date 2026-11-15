"""Fixtures for Astrion Remote tests."""

from __future__ import annotations

import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.astrion_remote.const import (
    CONF_APK_DIR,
    CONF_BASE_TOPIC,
    CONF_CONFIG,
    CONF_DEVICE_ID,
    DOMAIN,
)
from custom_components.astrion_remote.default_config import DEFAULT_CONFIG
from custom_components.astrion_remote.schema import validate_config

BASE = "astrion/ha100"


@pytest.fixture
async def hass(hass):
    """The frontend needs the hass_frontend package; mark it (and panel_custom) loaded so the
    integration's dependencies resolve. Panel registration only writes hass.data.
    assist_pipeline -> conversation needs the core `homeassistant` integration (exposed entities)."""
    hass.config.components.update({"frontend", "panel_custom"})
    assert await async_setup_component(hass, "homeassistant", {})
    return hass


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in every test."""
    return


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A configured remote with the default config."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Astrion Remote (ha100)",
        unique_id="ha100",
        data={CONF_DEVICE_ID: "ha100", CONF_BASE_TOPIC: BASE},
        options={CONF_CONFIG: validate_config(DEFAULT_CONFIG), CONF_APK_DIR: ""},
    )


@pytest.fixture
async def setup_entry(hass, mqtt_mock, config_entry):
    """Set up the integration with MQTT mocked."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The MQTT client's own periodic timer outlives the test (core MQTT behaviour)."""
    return True
