"""The Astrion Remote integration: configures the Astrion HA100 remote app over MQTT."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .apk import ApkDownloadView, ApkTokens
from .const import CONF_BASE_URL, DEFAULT_BASE_URL, DOMAIN, SERVICE_PAGE, SERVICE_RELOAD, SERVICE_TOAST
from .hub import AstrionHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR, Platform.UPDATE]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type AstrionConfigEntry = ConfigEntry[AstrionHub]

_TARGET = {vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string])}
TOAST_SCHEMA = vol.Schema({vol.Required("text"): vol.All(cv.string, vol.Length(min=1, max=500)), **_TARGET})
PAGE_SCHEMA = vol.Schema({vol.Required("id"): vol.All(cv.string, vol.Length(min=1)), **_TARGET})
RELOAD_SCHEMA = vol.Schema(_TARGET)


def _hubs_for_call(hass: HomeAssistant, call: ServiceCall) -> list[AstrionHub]:
    entries = [
        e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED
    ]
    if device_ids := call.data.get("device_id"):
        registry = dr.async_get(hass)
        wanted: set[str] = set()
        for device_id in device_ids:
            device = registry.async_get(device_id)
            if device is None:
                raise ServiceValidationError(f"Unknown device {device_id}")
            wanted.update(device.config_entries)
        entries = [e for e in entries if e.entry_id in wanted]
    if not entries:
        raise ServiceValidationError("No loaded Astrion remote matches")
    return [e.runtime_data for e in entries]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services and the APK download view."""
    tokens = ApkTokens()
    hass.data[DOMAIN] = {"tokens": tokens}
    hass.http.register_view(ApkDownloadView(tokens))

    async def toast(call: ServiceCall) -> None:
        text = " ".join(call.data["text"].split())  # one line on the wire
        for hub in _hubs_for_call(hass, call):
            await hub.async_send_cmd(f"toast {text}")

    async def page(call: ServiceCall) -> None:
        page_id = call.data["id"].strip()
        for hub in _hubs_for_call(hass, call):
            await hub.async_send_cmd(f"page {page_id}")

    async def reload(call: ServiceCall) -> None:
        for hub in _hubs_for_call(hass, call):
            await hub.async_publish_config()
            await hub.async_send_cmd("reload")

    hass.services.async_register(DOMAIN, SERVICE_TOAST, toast, schema=TOAST_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_PAGE, page, schema=PAGE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_RELOAD, reload, schema=RELOAD_SCHEMA)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: AstrionConfigEntry) -> bool:
    """1.1 -> 1.2: add the base_url option (HA URL reachable from the remote)."""
    if entry.version > 1:
        return False
    if entry.version == 1 and entry.minor_version < 2:
        options = dict(entry.options)
        options.setdefault(CONF_BASE_URL, DEFAULT_BASE_URL)
        hass.config_entries.async_update_entry(entry, options=options, minor_version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AstrionConfigEntry) -> bool:
    """Set up one remote."""
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("MQTT is not available")

    hub = AstrionHub(hass, entry)
    try:
        await hub.async_start()
    except HomeAssistantError as err:
        await hub.async_stop()
        raise ConfigEntryNotReady(str(err)) from err
    entry.runtime_data = hub

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: AstrionConfigEntry) -> None:
    """Options changed: publish the new config without reloading the entry."""
    await entry.runtime_data.async_apply_options()


async def async_unload_entry(hass: HomeAssistant, entry: AstrionConfigEntry) -> bool:
    """Unload a remote."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: AstrionConfigEntry) -> None:
    """Entry deleted: clear the retained config and mirrored states (best effort)."""
    if not mqtt.mqtt_config_entry_enabled(hass):
        return
    hub = AstrionHub(hass, entry)
    try:
        await hub.async_clear_retained()
    except HomeAssistantError as err:
        _LOGGER.warning("Could not clear retained Astrion topics: %s", err)
