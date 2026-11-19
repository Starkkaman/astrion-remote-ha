"""Admin-only websocket API used by the "Astrion Remote" sidebar panel and dashboard cards.

A stable contract (documented in the README): every stored-config response carries `version`;
config/set accepts the `version` it started from and rejects with `stale_config` on mismatch.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .config_events import config_version
from .const import (
    CONF_CONFIG,
    DOMAIN,
    GESTURES,
    HISENSE_IR,
    HISENSE_IR_ADDRESS,
    KEY_GROUPS,
    KEY_IDS,
    KEY_LABELS,
    RESET_PARTS,
    SCHEMA_VERSION,
    TV_KEYS,
)
from .default_config import DEFAULT_CONFIG
from .lint import async_lint
from .reset import ResetError, async_reset, async_undo_reset, has_previous
from .schema import validate_config

_LOGGER = logging.getLogger(__name__)

# How far back the recorder is asked for distinct context values (TV apps).
CONTEXT_HISTORY = timedelta(days=14)
CONTEXT_HISTORY_LIMIT = 2000
CONTEXT_MAX_VALUES = 50

_ENTRY = {vol.Required("entry_id"): str}

ERR_STALE_CONFIG = "stale_config"
STALE_CONFIG_MSG = "Someone else saved the remote config; reload and try again"


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register the panel's websocket commands."""
    websocket_api.async_register_command(hass, ws_config_get)
    websocket_api.async_register_command(hass, ws_config_validate)
    websocket_api.async_register_command(hass, ws_config_set)
    websocket_api.async_register_command(hass, ws_config_reset)
    websocket_api.async_register_command(hass, ws_config_undo_reset)
    websocket_api.async_register_command(hass, ws_tv_keys)


def _get_entry(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> ConfigEntry | None:
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Astrion remote not found")
        return None
    return entry


def _stored_config(entry: ConfigEntry) -> dict[str, Any]:
    return copy.deepcopy(entry.options.get(CONF_CONFIG) or DEFAULT_CONFIG)


def _key_list() -> list[dict[str, str]]:
    return [{"id": k, "label": KEY_LABELS.get(k, k), "group": KEY_GROUPS.get(k, "other")} for k in KEY_IDS]


def _format_errors(err: vol.Invalid) -> list[dict[str, Any]]:
    errors = err.errors if isinstance(err, vol.MultipleInvalid) else [err]
    return [
        {"path": [p if isinstance(p, (str, int)) else str(p) for p in e.path], "msg": e.msg}
        for e in errors
    ]


def _iter_action_paths(config: dict[str, Any]) -> Iterator[tuple[list[Any], Any]]:
    """(path, action) for every action slot, mirroring schema.iter_actions."""
    keys = config.get("keys")
    for key_id, key in (keys.items() if isinstance(keys, dict) else ()):
        if not isinstance(key, dict):
            continue
        for gesture in GESTURES:
            if gesture in key:
                yield ["keys", key_id, gesture], key[gesture]
        contexts = key.get("contexts")
        for ctx, actions in (contexts.items() if isinstance(contexts, dict) else ()):
            for gesture in GESTURES:
                if isinstance(actions, dict) and gesture in actions:
                    yield ["keys", key_id, "contexts", ctx, gesture], actions[gesture]
    pages = config.get("pages")
    for pi, page in enumerate(pages if isinstance(pages, list) else []):
        sections = page.get("sections") if isinstance(page, dict) else None
        for si, section in enumerate(sections if isinstance(sections, list) else []):
            if not isinstance(section, dict):
                continue
            base = ["pages", pi, "sections", si]
            for bi, button in enumerate(section.get("buttons") or []):
                yield [*base, "buttons", bi], button
            if "action" in section:
                yield [*base, "action"], section["action"]
            for ii, item in enumerate(section.get("items") or []):
                if isinstance(item, dict) and "action" in item:
                    yield [*base, "items", ii, "action"], item["action"]


def _page_ref_errors(config: Any) -> list[dict[str, Any]]:
    """Per-path errors for page actions pointing to unknown pages."""
    if not isinstance(config, dict) or not isinstance(config.get("pages"), list):
        return []
    ids = {p.get("id") for p in config["pages"] if isinstance(p, dict)} | {"next", "prev"}
    return [
        {"path": [*path, "page"], "msg": f"page action points to unknown page: {action.get('page')}"}
        for path, action in _iter_action_paths(config)
        if isinstance(action, dict) and action.get("type") == "page" and action.get("page") not in ids
    ]


def _validate(config: Any) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Return (validated config, []) or (None, errors)."""
    try:
        return validate_config(config), []
    except vol.Invalid as err:
        errors = _format_errors(err)
        if all(not e["path"] for e in errors) and (refs := _page_ref_errors(config)):
            return None, refs
        return None, errors
    except (TypeError, ValueError, KeyError, AttributeError) as err:
        return None, [{"path": [], "msg": f"invalid config: {err}"}]


def _recent_states(hass: HomeAssistant, entity_id: str) -> list[str]:
    """Distinct recent states of an entity, most recent first (runs in the recorder executor)."""
    from homeassistant.components.recorder import history

    start = dt_util.utcnow() - CONTEXT_HISTORY
    changes = history.state_changes_during_period(
        hass,
        start,
        None,
        entity_id,
        no_attributes=True,
        descending=True,
        limit=CONTEXT_HISTORY_LIMIT,
        include_start_time_state=True,
    )
    return [s.state for s in changes.get(entity_id.lower(), [])]


async def _context_values(hass: HomeAssistant, config: dict[str, Any]) -> list[str]:
    """Current + recent distinct states of tv.context_entity, plus existing override keys."""
    values: list[str] = []
    ctx_entity = (config.get("tv") or {}).get("context_entity")
    if isinstance(ctx_entity, str) and ctx_entity:
        if (state := hass.states.get(ctx_entity)) is not None:
            values.append(state.state)
        if "recorder" in hass.config.components:
            try:
                from homeassistant.components.recorder import get_instance

                values.extend(
                    await get_instance(hass).async_add_executor_job(_recent_states, hass, ctx_entity)
                )
            except Exception as err:  # noqa: BLE001 - history is a nicety, never fatal
                _LOGGER.debug("Could not read history of %s: %s", ctx_entity, err)
    keys = config.get("keys")
    if isinstance(keys, dict):
        for key in keys.values():
            contexts = key.get("contexts") if isinstance(key, dict) else None
            if isinstance(contexts, dict):
                values.extend(str(c) for c in contexts)
    seen: dict[str, None] = {}
    for value in values:
        if value and value not in (STATE_UNKNOWN, STATE_UNAVAILABLE) and len(seen) < CONTEXT_MAX_VALUES:
            seen.setdefault(value, None)
    # Override keys must always be offered, even past the cap.
    for key in keys.values() if isinstance(keys, dict) else ():
        if isinstance(key, dict) and isinstance(key.get("contexts"), dict):
            for ctx in key["contexts"]:
                seen.setdefault(str(ctx), None)
    return list(seen)


@websocket_api.websocket_command({vol.Required("type"): "astrion_remote/config/get", **_ENTRY})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_config_get(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the stored config, key list and context values."""
    if (entry := _get_entry(hass, connection, msg)) is None:
        return
    config = _stored_config(entry)
    version = config_version(config)
    connection.send_result(
        msg["id"],
        {
            "config": config,
            "version": version,
            "schema_version": SCHEMA_VERSION,
            "keys": _key_list(),
            "context_values": await _context_values(hass, config),
            "can_undo": has_previous(entry),
            "warnings": await async_lint(hass, config, _iter_action_paths(config)),
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "astrion_remote/config/validate", **_ENTRY, vol.Required("config"): dict}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_config_validate(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Validate a config without storing it; warnings never block a save."""
    if _get_entry(hass, connection, msg) is None:
        return
    config, errors = _validate(msg["config"])
    linted = config if config is not None else msg["config"]
    warnings = await async_lint(hass, linted, _iter_action_paths(linted))
    connection.send_result(msg["id"], {"ok": not errors, "errors": errors, "warnings": warnings})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "astrion_remote/config/set",
        **_ENTRY,
        vol.Required("config"): dict,
        # The version the editor loaded; omitted = last write wins (pre-0.6 clients).
        vol.Optional("version"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_config_set(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Validate, store in the entry options and publish (same path as the options flow)."""
    if (entry := _get_entry(hass, connection, msg)) is None:
        return
    # No await between this check and the store below, so two saves cannot interleave.
    if "version" in msg and msg["version"] != config_version(_stored_config(entry)):
        connection.send_error(msg["id"], ERR_STALE_CONFIG, STALE_CONFIG_MSG)
        return
    config, errors = _validate(msg["config"])
    if config is None:
        # Nothing is stored; the panel calls config/validate first for per-path errors.
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, _errors_text(errors))
        return
    changed = hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_CONFIG: config})
    # The update listener republishes on change; an unchanged save still republishes (explicit "Save").
    if not changed and entry.state is ConfigEntryState.LOADED:
        await entry.runtime_data.async_apply_options()
    connection.send_result(msg["id"], {"config": copy.deepcopy(config), "version": config_version(config)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "astrion_remote/config/reset",
        **_ENTRY,
        vol.Optional("parts", default=["pages"]): vol.All([vol.In(RESET_PARTS)], vol.Length(min=1)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_config_reset(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Replace parts with the defaults (the panel asks for confirmation first); same as the service."""
    if (entry := _get_entry(hass, connection, msg)) is None:
        return
    try:
        config = await async_reset(hass, entry, msg["parts"])
    except ResetError as err:
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, str(err))
        return
    connection.send_result(
        msg["id"], {"config": config, "version": config_version(config), "can_undo": has_previous(entry)}
    )


@websocket_api.websocket_command({vol.Required("type"): "astrion_remote/config/undo_reset", **_ENTRY})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_config_undo_reset(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Restore the config saved by the last reset; same as the service."""
    if (entry := _get_entry(hass, connection, msg)) is None:
        return
    try:
        config = await async_undo_reset(hass, entry)
    except ResetError as err:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, str(err))
        return
    connection.send_result(
        msg["id"], {"config": config, "version": config_version(config), "can_undo": has_previous(entry)}
    )


def _errors_text(errors: list[dict[str, Any]]) -> str:
    return "; ".join(f"{'.'.join(map(str, e['path'])) or 'config'}: {e['msg']}" for e in errors)


@websocket_api.websocket_command({vol.Required("type"): "astrion_remote/tv_keys"})
@websocket_api.require_admin
@callback
def ws_tv_keys(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """TV key names offered in the panel's picker (free text is accepted too), plus the Hisense IR codes."""
    ir_codes = [
        {"name": name, "protocol": "nec", "address": f"0x{HISENSE_IR_ADDRESS:04X}", "command": f"0x{cmd:02X}"}
        for name, cmd in HISENSE_IR
    ]
    connection.send_result(msg["id"], {"keys": list(TV_KEYS), "ir_codes": ir_codes})
