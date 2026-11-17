"""Reset parts of a remote's config to the current defaults, with a one-step undo.

Shared by the panel's websocket commands and the reset_to_defaults / undo_reset services.
"""

from __future__ import annotations

import copy
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_CONFIG, CONF_PREVIOUS_CONFIG, RESET_PARTS
from .default_config import DEFAULT_CONFIG
from .schema import validate_config


class ResetError(HomeAssistantError):
    """The reset or undo could not be applied (nothing was stored)."""


def stored_config(entry: ConfigEntry) -> dict[str, Any]:
    """The entry's config (the default if none is stored yet), as a copy."""
    return copy.deepcopy(entry.options.get(CONF_CONFIG) or DEFAULT_CONFIG)


def has_previous(entry: ConfigEntry) -> bool:
    """True if an undo is available."""
    return isinstance(entry.options.get(CONF_PREVIOUS_CONFIG), dict)


def reset_parts(config: dict[str, Any], parts: list[str]) -> dict[str, Any]:
    """Return a copy of `config` with each part in `parts` replaced by the current default."""
    out = copy.deepcopy(config)
    for part in parts:
        if part not in RESET_PARTS:
            raise ResetError(f"Unknown part {part!r} (expected any of {', '.join(RESET_PARTS)})")
        out[part] = copy.deepcopy(DEFAULT_CONFIG[part])
    return out


def _validated(config: dict[str, Any], what: str) -> dict[str, Any]:
    try:
        return validate_config(config)
    except vol.Invalid as err:
        raise ResetError(f"{what}: the resulting config is invalid ({err})") from err


async def _async_store(hass: HomeAssistant, entry: ConfigEntry, options: dict[str, Any]) -> None:
    """Store like a normal save: the update listener publishes; an unchanged save still publishes."""
    changed = hass.config_entries.async_update_entry(entry, options=options)
    if not changed and entry.state is ConfigEntryState.LOADED:
        await entry.runtime_data.async_apply_options()


async def async_reset(hass: HomeAssistant, entry: ConfigEntry, parts: list[str]) -> dict[str, Any]:
    """Replace `parts` with the defaults, keep the previous config for one undo; return the new config."""
    if not parts:
        raise ResetError("Nothing to reset")
    current = stored_config(entry)
    # e.g. default pages without a page that one of your keys opens -> refuse rather than store junk.
    config = _validated(reset_parts(current, list(dict.fromkeys(parts))), "Reset")
    await _async_store(
        hass, entry, {**entry.options, CONF_CONFIG: config, CONF_PREVIOUS_CONFIG: current}
    )
    return copy.deepcopy(config)


async def async_undo_reset(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Restore the config saved by the last reset (once); return it."""
    previous = entry.options.get(CONF_PREVIOUS_CONFIG)
    if not isinstance(previous, dict):
        raise ResetError("There is no reset to undo")
    config = _validated(previous, "Undo")
    options = {k: v for k, v in entry.options.items() if k != CONF_PREVIOUS_CONFIG}
    await _async_store(hass, entry, {**options, CONF_CONFIG: config})
    return copy.deepcopy(config)
