"""Smoke test: setup publishes the config."""

import json

from homeassistant.config_entries import ConfigEntryState

from .conftest import BASE


async def test_setup_publishes_config(hass, mqtt_mock, setup_entry):
    """Config is published retained on setup."""
    assert setup_entry.state is ConfigEntryState.LOADED
    calls = [c for c in mqtt_mock.async_publish.call_args_list if c.args[0] == f"{BASE}/config"]
    assert calls
    topic, payload, qos, retain = calls[-1].args
    assert retain is True
    doc = json.loads(payload)
    assert doc["schema_version"] == 1
    assert "script.turn_on:script.stereo_volume_up" in doc["allow"]


async def test_unload_and_remove_clears_retained(hass, mqtt_mock, setup_entry):
    """Unload keeps retained topics; removing the entry clears config and mirrored states."""
    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    await hass.async_block_till_done()
    assert setup_entry.state is ConfigEntryState.NOT_LOADED
    mqtt_mock.async_publish.reset_mock()
    await hass.config_entries.async_remove(setup_entry.entry_id)
    await hass.async_block_till_done()
    cleared = {c.args[0] for c in mqtt_mock.async_publish.call_args_list if c.args[1] == "" and c.args[3]}
    assert f"{BASE}/config" in cleared
    assert f"{BASE}/state/light.wled" in cleared
    assert f"{BASE}/state/sensor.hisense_tv_current_app" in cleared


async def test_failed_call_is_logged(hass, mqtt_mock, setup_entry, caplog):
    """A call that raises inside the service is logged, not propagated."""
    from pytest_homeassistant_custom_component.common import async_fire_mqtt_message

    # script.turn_on is not registered in tests -> ServiceNotFound (a HomeAssistantError)
    async_fire_mqtt_message(
        hass, f"{BASE}/call", json.dumps({"id": 9, "action": "script.turn_on", "target": {"entity_id": "script.stereo_power"}})
    )
    await hass.async_block_till_done()
    assert "call 9 script.turn_on failed" in caplog.text
