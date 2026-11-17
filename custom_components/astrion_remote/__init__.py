"""The Astrion Remote integration: configures the Astrion HA100 remote app over MQTT."""

from __future__ import annotations

import copy
import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .apk import ApkDownloadView, ApkTokens
from .const import (
    CONF_BASE_URL,
    CONF_CONFIG,
    DEFAULT_BASE_URL,
    DOMAIN,
    RESET_PARTS,
    SERVICE_PAGE,
    SERVICE_RELOAD,
    SERVICE_RESET_TO_DEFAULTS,
    SERVICE_TOAST,
    SERVICE_UNDO_RESET,
)
from .default_config import (
    DEFAULT_CONFIG,
    OLD_COLOUR_KEY_TAPS,
    OLD_DEFAULT_PAGES_0_3_0,
    OLD_VOICE_DEFAULTS,
)
from .hub import AstrionHub
from .panel import async_register_panel, async_register_static, async_remove_panel
from .reset import ResetError, async_reset, async_undo_reset
from .schema import ACTION, validate_pages
from .websocket import async_register as async_register_websocket

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.ASSIST_SATELLITE,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.UPDATE,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type AstrionConfigEntry = ConfigEntry[AstrionHub]

_TARGET = {vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string])}
TOAST_SCHEMA = vol.Schema({vol.Required("text"): vol.All(cv.string, vol.Length(min=1, max=500)), **_TARGET})
PAGE_SCHEMA = vol.Schema({vol.Required("id"): vol.All(cv.string, vol.Length(min=1)), **_TARGET})
RELOAD_SCHEMA = vol.Schema(_TARGET)
_ENTRY_ID = {vol.Optional("entry_id"): cv.string}
RESET_SCHEMA = vol.Schema(
    {**_ENTRY_ID, vol.Optional("parts", default=["pages"]): vol.All(cv.ensure_list, [vol.In(RESET_PARTS)])}
)
UNDO_RESET_SCHEMA = vol.Schema(_ENTRY_ID)


def _entry_for_call(hass: HomeAssistant, call: ServiceCall) -> ConfigEntry:
    """The entry named by `entry_id`, or the only one if there is exactly one."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if entry_id := call.data.get("entry_id"):
        entries = [e for e in entries if e.entry_id == entry_id]
        if not entries:
            raise ServiceValidationError(f"Unknown Astrion remote {entry_id}")
    elif len(entries) != 1:
        raise ServiceValidationError(
            "No Astrion remote is configured" if not entries else "Several remotes: give entry_id"
        )
    return entries[0]


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
    """Register services, the APK download view, the panel's websocket API and static files."""
    tokens = ApkTokens()
    integration = await async_get_integration(hass, DOMAIN)
    hass.data[DOMAIN] = {"tokens": tokens, "version": str(integration.version or "0")}
    hass.http.register_view(ApkDownloadView(tokens))
    async_register_websocket(hass)
    await async_register_static(hass)
    # The editor stays usable while MQTT is down (saves go to the options and publish on setup).
    await async_register_panel(hass, hass.data[DOMAIN]["version"])

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
    async def reset_to_defaults(call: ServiceCall) -> None:
        try:
            await async_reset(hass, _entry_for_call(hass, call), call.data["parts"])
        except ResetError as err:
            raise ServiceValidationError(str(err)) from err

    async def undo_reset(call: ServiceCall) -> None:
        try:
            await async_undo_reset(hass, _entry_for_call(hass, call))
        except ResetError as err:
            raise ServiceValidationError(str(err)) from err

    hass.services.async_register(DOMAIN, SERVICE_RELOAD, reload, schema=RELOAD_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_RESET_TO_DEFAULTS, reset_to_defaults, schema=RESET_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_UNDO_RESET, undo_reset, schema=UNDO_RESET_SCHEMA)
    return True


def migrate_voice_key(config: dict[str, Any]) -> dict[str, Any] | None:
    """Return a copy of `config` with the new voice key default, or None to leave it alone.

    Only a voice key that is still exactly the pre-0.3.0 default (tv SEARCH on tap, nothing
    else) is replaced; any other mapping is the user's and is kept.
    """
    keys = config.get("keys")
    if not isinstance(keys, dict) or keys.get("voice") not in OLD_VOICE_DEFAULTS:
        return None
    out = copy.deepcopy(config)
    out["keys"]["voice"] = copy.deepcopy(DEFAULT_CONFIG["keys"]["voice"])
    return out


def _same_action(a: Any, b: dict[str, Any]) -> bool:
    try:
        return ACTION(a) == ACTION(b)
    except vol.Invalid:
        return False


def _same_pages(a: Any, b: list[dict[str, Any]]) -> bool:
    try:
        return validate_pages(a) == validate_pages(b)
    except vol.Invalid:
        return False


def migrate_v3_defaults(config: dict[str, Any]) -> dict[str, Any] | None:
    """Return a copy of `config` moved to the v3 defaults where untouched, or None if nothing changes.

    - A colour key's tap is replaced only if it is still exactly the 0.3.0 select_next cycle.
    - Pages are replaced only if they still equal the 0.3.0 default pages; otherwise kept.
    - The theme is the user's choice and is never touched.
    """
    out = copy.deepcopy(config)
    changed = False
    keys = out.get("keys")
    if isinstance(keys, dict):
        for colour, old_tap in OLD_COLOUR_KEY_TAPS.items():
            key = keys.get(colour)
            if isinstance(key, dict) and _same_action(key.get("tap"), old_tap):
                key["tap"] = copy.deepcopy(DEFAULT_CONFIG["keys"][colour]["tap"])
                changed = True
    if _same_pages(out.get("pages"), OLD_DEFAULT_PAGES_0_3_0):
        out["pages"] = copy.deepcopy(DEFAULT_CONFIG["pages"])
        changed = True
    else:
        _LOGGER.info("Astrion: pages differ from the 0.3.0 default; keeping your pages (v3 layout not applied)")
    return out if changed else None


async def async_migrate_entry(hass: HomeAssistant, entry: AstrionConfigEntry) -> bool:
    """1.1 -> 1.2: add the base_url option (HA URL reachable from the remote).

    1.2 -> 1.3: voice key tap/hold -> voice ha/tv, if it is still the old default.

    1.3 -> 1.4: v3 defaults (choose on colour keys, new pages), only where still the 0.3.0 default.
    """
    if entry.version > 1:
        return False
    if entry.version == 1 and entry.minor_version < 2:
        options = dict(entry.options)
        options.setdefault(CONF_BASE_URL, DEFAULT_BASE_URL)
        hass.config_entries.async_update_entry(entry, options=options, minor_version=2)
    if entry.version == 1 and entry.minor_version < 3:
        options = dict(entry.options)
        if isinstance(config := options.get(CONF_CONFIG), dict) and (
            migrated := migrate_voice_key(config)
        ) is not None:
            options[CONF_CONFIG] = migrated
        hass.config_entries.async_update_entry(entry, options=options, minor_version=3)
    if entry.version == 1 and entry.minor_version < 4:
        options = dict(entry.options)
        if isinstance(config := options.get(CONF_CONFIG), dict) and (
            migrated := migrate_v3_defaults(config)
        ) is not None:
            options[CONF_CONFIG] = migrated
        hass.config_entries.async_update_entry(entry, options=options, minor_version=4)
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
    # Re-adds the panel if the last remote was deleted and a new one added in the same run.
    await async_register_panel(hass, hass.data[DOMAIN]["version"])
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
    """Entry deleted: drop the panel with the last remote; clear retained topics (best effort)."""
    if not [e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id]:
        async_remove_panel(hass)
    if not mqtt.mqtt_config_entry_enabled(hass):
        return
    hub = AstrionHub(hass, entry)
    try:
        await hub.async_clear_retained()
    except HomeAssistantError as err:
        _LOGGER.warning("Could not clear retained Astrion topics: %s", err)
