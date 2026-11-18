"""Device triggers: every key x (tap, double, hold), plus picked up / put down (motion)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, EVENT_BUTTON, EVENT_MOTION, GESTURES, KEY_IDS, MOTION_STATES

CONF_SUBTYPE = "subtype"

_KEY_TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {vol.Required(CONF_TYPE): vol.In(GESTURES), vol.Required(CONF_SUBTYPE): vol.In(KEY_IDS)}
)
_MOTION_TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend({vol.Required(CONF_TYPE): vol.In(MOTION_STATES)})
TRIGGER_SCHEMA = vol.Any(_KEY_TRIGGER_SCHEMA, _MOTION_TRIGGER_SCHEMA)


async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict[str, Any]]:
    """List triggers for an Astrion remote device."""
    return [
        {
            CONF_PLATFORM: "device",
            CONF_DOMAIN: DOMAIN,
            CONF_DEVICE_ID: device_id,
            CONF_TYPE: gesture,
            CONF_SUBTYPE: key,
        }
        for key in KEY_IDS
        for gesture in GESTURES
    ] + [
        {CONF_PLATFORM: "device", CONF_DOMAIN: DOMAIN, CONF_DEVICE_ID: device_id, CONF_TYPE: state}
        for state in MOTION_STATES
    ]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a trigger as an event trigger on astrion_remote_button (keys) or astrion_remote_motion."""
    if config[CONF_TYPE] in MOTION_STATES:
        event_type = EVENT_MOTION
        event_data = {CONF_DEVICE_ID: config[CONF_DEVICE_ID], "state": config[CONF_TYPE]}
    else:
        event_type = EVENT_BUTTON
        event_data = {
            CONF_DEVICE_ID: config[CONF_DEVICE_ID],
            "key": config[CONF_SUBTYPE],
            "gesture": config[CONF_TYPE],
        }
    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: event_type,
            event_trigger.CONF_EVENT_DATA: event_data,
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )
