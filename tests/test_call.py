"""<base>/call handling against the allowlist."""

import json
import logging

from pytest_homeassistant_custom_component.common import async_fire_mqtt_message, async_mock_service

from .conftest import BASE


async def _call(hass, payload):
    async_fire_mqtt_message(hass, f"{BASE}/call", json.dumps(payload))
    await hass.async_block_till_done()


async def test_allowed_call_executes(hass, mqtt_mock, setup_entry):
    """An allowlisted action+entity is executed."""
    calls = async_mock_service(hass, "script", "turn_on")
    lights = async_mock_service(hass, "light", "turn_on")
    await _call(
        hass,
        {"id": 1, "action": "script.turn_on", "target": {"entity_id": "script.stereo_volume_up"}, "data": {}},
    )
    assert len(calls) == 1
    assert calls[0].data["entity_id"] == ["script.stereo_volume_up"]

    # natural action of a rocker entity, with data
    await _call(
        hass,
        {"id": 2, "action": "light.turn_on", "target": {"entity_id": ["light.living_room"]}, "data": {"brightness": 99}},
    )
    assert len(lights) == 1
    assert lights[0].data["brightness"] == 99


async def test_disallowed_calls_refused_and_logged(hass, mqtt_mock, setup_entry, caplog):
    """Anything outside the allowlist is refused and logged."""
    locks = async_mock_service(hass, "lock", "unlock")
    lights = async_mock_service(hass, "light", "turn_on")
    scripts = async_mock_service(hass, "script", "turn_on")
    caplog.set_level(logging.WARNING)

    await _call(hass, {"id": 3, "action": "lock.unlock", "target": {"entity_id": "lock.front_door"}})
    assert not locks
    assert "refused call 3" in caplog.text and "lock.unlock" in caplog.text

    # mixing an allowed entity with a forbidden one
    await _call(
        hass,
        {"id": 4, "action": "light.turn_on", "target": {"entity_id": ["light.living_room", "light.bedroom"]}},
    )
    # smuggling entity_id through data
    await _call(hass, {"id": 5, "action": "light.turn_on", "data": {"entity_id": "light.bedroom"}})
    # area targets are never allowed
    await _call(hass, {"id": 6, "action": "light.turn_on", "target": {"area_id": "living_room"}})
    # untargeted call of a targeted action
    await _call(hass, {"id": 7, "action": "script.turn_on"})
    # garbage
    async_fire_mqtt_message(hass, f"{BASE}/call", "not json")
    await hass.async_block_till_done()

    assert not lights and not scripts
    for call_id in (4, 5, 6, 7):
        assert f"refused call {call_id}" in caplog.text
    assert "malformed call payload" in caplog.text


async def test_data_entity_id_counts_as_target(hass, mqtt_mock, setup_entry):
    """data.entity_id of an allowed entity works (folded into the target)."""
    scripts = async_mock_service(hass, "script", "turn_on")
    await _call(hass, {"id": 8, "action": "script.turn_on", "data": {"entity_id": "script.stereo_power"}})
    assert len(scripts) == 1
    assert scripts[0].data["entity_id"] == ["script.stereo_power"]
