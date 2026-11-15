"""State mirror: publish, throttle, clear."""

from datetime import timedelta
import json
from unittest.mock import patch

from homeassistant.core_config import async_process_ha_core_config
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.astrion_remote.const import CONF_CONFIG

from .conftest import BASE

LAMP = "light.living_room_floor_lamp"


def _state_calls(mqtt_mock, entity_id):
    return [c.args for c in mqtt_mock.async_publish.call_args_list if c.args[0] == f"{BASE}/state/{entity_id}"]


async def test_initial_publish_and_attributes(hass, mqtt_mock, config_entry):
    """Referenced entities are published retained with the attribute subset."""
    await async_process_ha_core_config(hass, {"internal_url": "http://ha.local:8123"})
    hass.states.async_set(LAMP, "on", {"brightness": 128, "friendly_name": "Lamp", "secret_attr": "x"})
    hass.states.async_set(
        "media_player.phoster_3",
        "playing",
        {"media_title": "Ep 1", "media_series_title": "Show", "entity_picture": "/api/media_player_proxy/x?token=t"},
    )
    hass.states.async_set("light.not_referenced", "on")
    config_entry.add_to_hass(hass)
    with patch("custom_components.astrion_remote.hub._monotonic", return_value=1000.0):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    (topic, payload, qos, retain) = _state_calls(mqtt_mock, LAMP)[-1]
    assert retain is True
    assert json.loads(payload) == {"s": "on", "a": {"friendly_name": "Lamp", "brightness": 128}}
    media = json.loads(_state_calls(mqtt_mock, "media_player.phoster_3")[-1][1])
    assert media["a"]["media_series_title"] == "Show"
    assert media["a"]["entity_picture"] == "http://ha.local:8123/api/media_player_proxy/x?token=t"
    # context entity is mirrored even though no page names it; missing entity -> unavailable
    ctx = json.loads(_state_calls(mqtt_mock, "sensor.hisense_tv_current_app")[-1][1])
    assert ctx == {"s": "unavailable", "a": {}}
    assert not _state_calls(mqtt_mock, "light.not_referenced")


async def test_throttle_coalesces(hass, mqtt_mock, config_entry):
    """At most one publish per 250 ms per entity; the trailing publish carries the latest state."""
    clock = [1000.0]
    with patch("custom_components.astrion_remote.hub._monotonic", side_effect=lambda: clock[0]):
        config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        before = len(_state_calls(mqtt_mock, LAMP))

        clock[0] += 1.0
        hass.states.async_set(LAMP, "on", {"brightness": 10})
        await hass.async_block_till_done()
        assert len(_state_calls(mqtt_mock, LAMP)) == before + 1  # immediate

        clock[0] += 0.05
        hass.states.async_set(LAMP, "on", {"brightness": 20})
        hass.states.async_set(LAMP, "on", {"brightness": 30})
        hass.states.async_set(LAMP, "on", {"brightness": 40})
        await hass.async_block_till_done()
        assert len(_state_calls(mqtt_mock, LAMP)) == before + 1  # held back

        clock[0] += 0.3
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
        await hass.async_block_till_done()
        calls = _state_calls(mqtt_mock, LAMP)
        assert len(calls) == before + 2
        assert json.loads(calls[-1][1])["a"]["brightness"] == 40


async def test_unreferenced_entity_is_cleared(hass, mqtt_mock, setup_entry):
    """Dropping an entity from the config publishes an empty retained payload."""
    config = dict(setup_entry.options[CONF_CONFIG])
    config["pages"] = [p for p in config["pages"] if p["id"] != "room"]
    hass.config_entries.async_update_entry(setup_entry, options={**setup_entry.options, CONF_CONFIG: config})
    await hass.async_block_till_done()

    topic, payload, qos, retain = _state_calls(mqtt_mock, "light.wled")[-1]
    assert payload == "" and retain is True
    # still referenced by a key (vol_up hold) -> not cleared
    assert _state_calls(mqtt_mock, "script.stereo_volume_up")[-1][1] != ""
    hub = setup_entry.runtime_data
    assert "light.wled" not in hub.mirrored

    # later state changes of the dropped entity are no longer published
    n = len(_state_calls(mqtt_mock, "light.wled"))
    hass.states.async_set("light.wled", "on")
    await hass.async_block_till_done()
    assert len(_state_calls(mqtt_mock, "light.wled")) == n


async def test_stale_entities_cleared_after_restart(hass, mqtt_mock, config_entry, hass_storage):
    """Entities mirrored before a restart but no longer referenced are cleared on setup."""
    hass_storage[f"astrion_remote.{config_entry.entry_id}"] = {
        "version": 1,
        "key": f"astrion_remote.{config_entry.entry_id}",
        "data": {"mirrored": ["light.old_one", LAMP]},
    }
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert _state_calls(mqtt_mock, "light.old_one")[-1][1:] == ("", 1, True)
