"""Config versions (optimistic concurrency) and the `astrion_remote_config_changed` event.

Several editors (the sidebar panel, dashboard cards) can edit the same remote. Every stored config
has a `version`: the first 16 hex digits of the sha256 of its canonical JSON. Saves may pass the
version they started from; a mismatch means someone else saved in between.

Whenever an entry's stored config changes, by any path (websocket save, reset, undo, the options
flow, the services), `astrion_remote_config_changed` {entry_id, version} is fired on the HA bus.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    ConfigEntry,
    ConfigEntryChange,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import CONF_CONFIG, DOMAIN, EVENT_CONFIG_CHANGED
from .default_config import DEFAULT_CONFIG


def config_version(config: Any) -> str:
    """Stable short hash of a config: sha256 of its canonical JSON, first 16 hex digits."""
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def entry_config_version(entry: ConfigEntry) -> str:
    """Version of the entry's stored config (the default if none is stored yet)."""
    return config_version(entry.options.get(CONF_CONFIG) or DEFAULT_CONFIG)


@callback
def async_track_config_changes(hass: HomeAssistant, versions: dict[str, str]) -> None:
    """Fire EVENT_CONFIG_CHANGED whenever an entry's stored config changes (any store path)."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        versions[entry.entry_id] = entry_config_version(entry)

    @callback
    def _changed(change: ConfigEntryChange, entry: ConfigEntry) -> None:
        if entry.domain != DOMAIN:
            return
        if change is ConfigEntryChange.REMOVED:
            versions.pop(entry.entry_id, None)
            return
        version = entry_config_version(entry)
        previous = versions.get(entry.entry_id)
        versions[entry.entry_id] = version
        if change is ConfigEntryChange.UPDATED and version != previous:
            hass.bus.async_fire(EVENT_CONFIG_CHANGED, {"entry_id": entry.entry_id, "version": version})

    # Lives as long as HA: the integration's async_setup runs once per run.
    async_dispatcher_connect(hass, SIGNAL_CONFIG_ENTRY_CHANGED, _changed)
