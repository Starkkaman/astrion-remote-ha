"""<base>/event -> astrion_remote_button + device triggers."""

import json

from homeassistant.components import automation
from homeassistant.components.device_automation import DeviceAutomationType
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_mqtt_message,
    async_get_device_automations,
)

from custom_components.astrion_remote.const import DOMAIN, GESTURES, KEY_IDS

from .conftest import BASE


async def test_event_fires_bus_event(hass, mqtt_mock, setup_entry):
    """A key event becomes astrion_remote_button with the HA device id."""
    events = async_capture_events(hass, "astrion_remote_button")
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, "ha100"), setup_entry.entry_id)
    async_fire_mqtt_message(
        hass, f"{BASE}/event", json.dumps({"key": "red", "gesture": "hold", "ctx": "jamfin", "ts": 1})
    )
    async_fire_mqtt_message(hass, f"{BASE}/event", json.dumps({"key": "red", "gesture": "wiggle"}))
    async_fire_mqtt_message(hass, f"{BASE}/event", "garbage")
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data == {
        "device_id": device.id,
        "remote_id": "ha100",
        "key": "red",
        "gesture": "hold",
        "ctx": "jamfin",
    }


async def test_device_triggers(hass, mqtt_mock, setup_entry):
    """Every key x gesture is offered and fires an automation."""
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, "ha100"), setup_entry.entry_id)
    assert device.name == "Astrion Remote"
    triggers = await async_get_device_automations(hass, DeviceAutomationType.TRIGGER, device.id)
    ours = {(t["subtype"], t["type"]) for t in triggers if t["domain"] == DOMAIN}
    assert ours == {(k, g) for k in KEY_IDS for g in GESTURES}

    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: [
                {
                    "triggers": {
                        "platform": "device",
                        "domain": DOMAIN,
                        "device_id": device.id,
                        "type": "tap",
                        "subtype": "power",
                    },
                    "actions": {"event": "power_pressed"},
                }
            ]
        },
    )
    fired = async_capture_events(hass, "power_pressed")
    async_fire_mqtt_message(hass, f"{BASE}/event", json.dumps({"key": "power", "gesture": "double"}))
    await hass.async_block_till_done()
    assert not fired
    async_fire_mqtt_message(hass, f"{BASE}/event", json.dumps({"key": "power", "gesture": "tap"}))
    await hass.async_block_till_done()
    assert len(fired) == 1
