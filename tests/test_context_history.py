"""Context values (TV apps) offered by config/get come from the recorder when it is loaded."""

import pytest
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """The recorder must be set up before hass (overrides the conftest autouse fixture)."""
    return


async def _send(client, payload):
    await client.send_json_auto_id(payload)
    return await client.receive_json()


async def test_context_values_from_recorder(hass, mqtt_mock, setup_entry, hass_ws_client):
    """Recent distinct states of the context entity come from the recorder, current first."""
    for app in ("com.netflix", "com.plex", "unavailable", "com.netflix", "com.kodi"):
        hass.states.async_set("sensor.hisense_tv_current_app", app)
        await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    client = await hass_ws_client(hass)
    msg = await _send(client, {"type": "astrion_remote/config/get", "entry_id": setup_entry.entry_id})
    values = msg["result"]["context_values"]
    assert values[0] == "com.kodi"
    assert set(values) >= {"com.netflix", "com.plex", "com.kodi"}
    assert "unavailable" not in values
    assert len(values) == len(set(values))
