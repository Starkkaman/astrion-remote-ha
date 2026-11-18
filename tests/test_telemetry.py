"""Telemetry and status -> entities; buttons; services."""

import json

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import async_fire_mqtt_message

from custom_components.astrion_remote.const import DOMAIN

from .conftest import BASE

TELEMETRY = {
    "battery": 87,
    "charging": True,
    "screen": "on",
    "page": "watch",
    "app_version": "0.3.1",
    "wifi_rssi": -61,
    "last_key": "red",
    "ts": 1731628800,
}


async def test_telemetry_to_entities(hass, mqtt_mock, setup_entry):
    """Retained telemetry fills the sensors; status drives connectivity/availability."""
    assert hass.states.get("sensor.astrion_remote_battery").state == STATE_UNAVAILABLE
    async_fire_mqtt_message(hass, f"{BASE}/status", "online", retain=True)
    async_fire_mqtt_message(hass, f"{BASE}/telemetry", json.dumps(TELEMETRY), retain=True)
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.astrion_remote_connected").state == STATE_ON
    battery = hass.states.get("sensor.astrion_remote_battery")
    assert battery.state == "87"
    assert battery.attributes["unit_of_measurement"] == "%"
    assert hass.states.get("binary_sensor.astrion_remote_charging").state == STATE_ON
    assert hass.states.get("binary_sensor.astrion_remote_screen").state == STATE_ON
    assert hass.states.get("sensor.astrion_remote_page").state == "watch"
    assert hass.states.get("sensor.astrion_remote_app_version").state == "0.3.1"
    assert hass.states.get("sensor.astrion_remote_wi_fi_signal").state == "-61"
    assert hass.states.get("sensor.astrion_remote_last_key").state == "red"
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, "ha100"), setup_entry.entry_id)
    assert device.sw_version == "0.3.1"

    # partial update merges
    async_fire_mqtt_message(hass, f"{BASE}/telemetry", json.dumps({"charging": False, "screen": False}))
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.astrion_remote_charging").state == STATE_OFF
    assert hass.states.get("binary_sensor.astrion_remote_screen").state == STATE_OFF
    assert hass.states.get("sensor.astrion_remote_battery").state == "87"

    # live (non-initial) messages arrive with retain=False
    async_fire_mqtt_message(hass, f"{BASE}/status", "offline")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.astrion_remote_connected").state == STATE_OFF
    assert hass.states.get("sensor.astrion_remote_battery").state == STATE_UNAVAILABLE


def _cmds(mqtt_mock):
    return [c.args for c in mqtt_mock.async_publish.call_args_list if c.args[0] == f"{BASE}/cmd"]


async def test_new_telemetry_fields(hass, mqtt_mock, setup_entry):
    """picked_up, kiosk and stock_suspended (app 0.6) map to entities; unknown kiosk values are dropped."""
    async_fire_mqtt_message(hass, f"{BASE}/status", "online", retain=True)
    async_fire_mqtt_message(
        hass,
        f"{BASE}/telemetry",
        json.dumps({"picked_up": True, "kiosk": "paused", "stock_suspended": False, "update_error": None}),
    )
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.astrion_remote_picked_up").state == STATE_ON
    kiosk = hass.states.get("sensor.astrion_remote_kiosk")
    assert kiosk.state == "paused"
    assert kiosk.attributes["options"] == ["on", "off", "paused"]
    assert hass.states.get("binary_sensor.astrion_remote_stock_app_suspended").state == STATE_OFF

    async_fire_mqtt_message(
        hass, f"{BASE}/telemetry", json.dumps({"picked_up": None, "kiosk": "weird", "stock_suspended": "on"})
    )
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.astrion_remote_picked_up").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.astrion_remote_kiosk").state == STATE_UNAVAILABLE
    assert hass.states.get("binary_sensor.astrion_remote_stock_app_suspended").state == STATE_ON


async def test_buttons_and_services(hass, mqtt_mock, setup_entry):
    """Buttons and services publish non-retained commands."""
    mqtt_mock.async_publish.reset_mock()
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.astrion_remote_go_to_home_page"}, blocking=True
    )
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.astrion_remote_reload_config"}, blocking=True
    )
    await hass.services.async_call(DOMAIN, "toast", {"text": "Dinner\nis ready"}, blocking=True)
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, "ha100"), setup_entry.entry_id)
    await hass.services.async_call(DOMAIN, "page", {"id": "music", "device_id": device.id}, blocking=True)
    await hass.services.async_call(DOMAIN, "reload", {}, blocking=True)

    cmds = _cmds(mqtt_mock)
    assert [c[1] for c in cmds] == ["page now", "reload", "toast Dinner is ready", "page music", "reload"]
    assert all(c[3] is False for c in cmds)
    configs = [c.args for c in mqtt_mock.async_publish.call_args_list if c.args[0] == f"{BASE}/config"]
    assert len(configs) == 2 and all(c[3] is True for c in configs)
