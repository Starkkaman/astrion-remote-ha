"""Remote config schema (schema_version 1), allowlist and entity reference helpers.

The config format is the contract in docs/ARCHITECTURE.md. Everything here is pure
(no hass access) so it can be reused by the options flow and tested in isolation.
"""

from __future__ import annotations

from collections.abc import Iterator
import copy
import re
from typing import Any

import voluptuous as vol

from .const import (
    APP_CMDS,
    GESTURES,
    KEY_IDS,
    SCHEMA_VERSION,
    THEME_MODES,
    TV_HOLD_MODES,
    VOICE_TARGETS,
)

_ENTITY_ID_RE = re.compile(r"^(?!.+__)(?!_)[\da-z_]+(?<!_)\.(?!_)[\da-z_]+(?<!_)$")
_ACTION_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


def entity_id(value: Any) -> str:
    """Validate a single entity id."""
    if not isinstance(value, str) or not _ENTITY_ID_RE.match(value.strip().lower()):
        raise vol.Invalid(f"invalid entity id: {value!r}")
    return value.strip().lower()


def entity_ids(value: Any) -> list[str]:
    """Validate a string or list of entity ids into a list."""
    if isinstance(value, str):
        value = [v for v in (x.strip() for x in value.split(",")) if v]
    if not isinstance(value, list) or not value:
        raise vol.Invalid("expected one or more entity ids")
    return [entity_id(v) for v in value]


def action_name(value: Any) -> str:
    """Validate a `domain.service` action name."""
    if not isinstance(value, str) or not _ACTION_RE.match(value.strip()):
        raise vol.Invalid(f"invalid action: {value!r} (expected domain.service)")
    return value.strip()


# Targets are restricted to entity ids so the allowlist (action:entity) stays exact.
TARGET_SCHEMA = vol.Schema({vol.Required("entity_id"): entity_ids})

_DECORATION = {vol.Optional("label"): str, vol.Optional("icon"): str}

_ACTION_SCHEMAS: dict[str, dict[Any, Any]] = {
    "tv_key": {
        vol.Required("key"): vol.All(str, vol.Length(min=1)),
        vol.Optional("hold"): vol.In(TV_HOLD_MODES),
    },
    "ha": {
        vol.Required("action"): action_name,
        vol.Optional("target"): TARGET_SCHEMA,
        vol.Optional("data"): dict,
        # Only meaningful for `hold`: the app re-sends the call every keepalive_ms.
        vol.Optional("repeat"): bool,
    },
    "event": {},
    "page": {vol.Required("page"): vol.All(str, vol.Length(min=1))},
    "app": {vol.Required("cmd"): vol.In(APP_CMDS)},
    # ha = HA Assist through the integration's assist_satellite; tv = Google Assistant on the TV.
    "voice": {vol.Required("target"): vol.In(VOICE_TARGETS)},
    "none": {},
}


def _ha_data_check(action: dict[str, Any]) -> dict[str, Any]:
    data = action.get("data") or {}
    for forbidden in ("area_id", "device_id", "floor_id", "label_id"):
        if forbidden in data:
            raise vol.Invalid(f"ha action data may not contain {forbidden}; use target.entity_id")
    if "entity_id" in data:
        # Fold legacy data.entity_id into the target so the allowlist sees it.
        ids = entity_ids(data.pop("entity_id"))
        target = action.setdefault("target", {"entity_id": []})
        target["entity_id"] = list(dict.fromkeys([*target.get("entity_id", []), *ids]))
        if not data:
            action.pop("data", None)
    return action


def _make_action_validator(decorated: bool):
    schemas = {
        typ: vol.Schema(
            {vol.Required("type"): typ, **fields, **(_DECORATION if decorated else {})}
        )
        for typ, fields in _ACTION_SCHEMAS.items()
    }

    def validate(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise vol.Invalid("action must be a mapping")
        typ = value.get("type")
        if typ not in schemas:
            raise vol.Invalid(f"unknown action type: {typ!r}")
        out = schemas[typ](copy.deepcopy(value))
        if typ == "ha":
            out = _ha_data_check(out)
        return out

    return validate


ACTION = _make_action_validator(decorated=False)
DECORATED_ACTION = _make_action_validator(decorated=True)

GESTURE_MAP = {vol.Optional(g): ACTION for g in GESTURES}

KEY_SCHEMA = vol.Schema(
    {**GESTURE_MAP, vol.Optional("contexts"): {vol.All(str, vol.Length(min=1)): GESTURE_MAP}}
)

TILE_SCHEMA = vol.Schema(
    {
        vol.Required("label"): str,
        vol.Optional("sub"): str,
        vol.Optional("icon"): str,
        vol.Optional("entity"): entity_id,
        vol.Optional("action"): ACTION,
    }
)

_SECTION_SCHEMAS: dict[str, vol.Schema] = {
    "now_playing": vol.Schema(
        {
            vol.Required("type"): "now_playing",
            vol.Required("entity"): entity_id,
            vol.Optional("title"): str,
            vol.Optional("buttons", default=list): [DECORATED_ACTION],
        }
    ),
    "tiles": vol.Schema(
        {
            vol.Required("type"): "tiles",
            vol.Optional("title"): str,
            vol.Optional("columns", default=3): vol.All(int, vol.Range(min=1, max=3)),
            vol.Required("items"): [TILE_SCHEMA],
        }
    ),
    "segmented": vol.Schema(
        {
            vol.Required("type"): "segmented",
            vol.Required("entity"): vol.All(
                entity_id, vol.Match(r"^(select|input_select)\.", msg="segmented needs a select/input_select")
            ),
            vol.Optional("title"): str,
            vol.Optional("options"): [str],
        }
    ),
    "slider": vol.Schema(
        {
            vol.Required("type"): "slider",
            vol.Required("entity"): entity_id,
            vol.Optional("title"): str,
            vol.Optional("action"): ACTION,
        }
    ),
    "rocker": vol.Schema(
        {
            vol.Required("type"): "rocker",
            vol.Required("entity"): entity_id,
            vol.Optional("title"): str,
        }
    ),
    "switch": vol.Schema(
        {
            vol.Required("type"): "switch",
            vol.Required("entity"): entity_id,
            vol.Optional("title"): str,
        }
    ),
    "keys": vol.Schema(
        {
            vol.Required("type"): "keys",
            vol.Optional("title"): str,
            vol.Required("items"): [
                vol.Schema({vol.Required("label"): str, vol.Optional("icon"): str, vol.Required("action"): ACTION})
            ],
        }
    ),
}


def SECTION(value: Any) -> dict[str, Any]:  # noqa: N802
    """Validate a page section by its type."""
    if not isinstance(value, dict):
        raise vol.Invalid("section must be a mapping")
    typ = value.get("type")
    if typ not in _SECTION_SCHEMAS:
        raise vol.Invalid(f"unknown section type: {typ!r}")
    return _SECTION_SCHEMAS[typ](value)


PAGE_SCHEMA = vol.Schema(
    {
        vol.Required("id"): vol.All(str, vol.Match(r"^[a-z0-9_-]+$", msg="page id must be [a-z0-9_-]")),
        vol.Required("title"): str,
        vol.Optional("icon"): str,
        vol.Optional("sections", default=list): [SECTION],
    }
)


def _unique_ids(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    for page in pages:
        if page["id"] in seen or page["id"] in ("next", "prev"):
            raise vol.Invalid(f"duplicate or reserved page id: {page['id']}")
        seen.add(page["id"])
    return pages


PAGES_SCHEMA = vol.All([PAGE_SCHEMA], vol.Length(min=1), _unique_ids)

TIMINGS_SCHEMA = vol.Schema(
    {
        vol.Optional("hold_ms", default=450): vol.All(int, vol.Range(min=100, max=3000)),
        vol.Optional("double_ms", default=350): vol.All(int, vol.Range(min=100, max=2000)),
        vol.Optional("keepalive_ms", default=300): vol.All(int, vol.Range(min=50, max=3000)),
    }
)
TV_SCHEMA = vol.Schema(
    {
        vol.Optional("keytopic", default="controlfreak/hisense_tv/key/set"): vol.All(
            str, vol.Match(r"^[^#+]+$", msg="keytopic may not contain wildcards")
        ),
        vol.Optional("context_entity"): vol.Any(None, entity_id),
    }
)
THEME_SCHEMA = vol.Schema(
    {
        vol.Optional("mode", default="auto"): vol.In(THEME_MODES),
        vol.Optional("calm", default=False): bool,
    }
)

_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional("schema_version", default=SCHEMA_VERSION): SCHEMA_VERSION,
        vol.Optional("timings", default=dict): TIMINGS_SCHEMA,
        vol.Optional("tv", default=dict): TV_SCHEMA,
        vol.Optional("theme", default=dict): THEME_SCHEMA,
        vol.Optional("keys", default=dict): {vol.In(KEY_IDS): KEY_SCHEMA},
        vol.Required("pages"): PAGES_SCHEMA,
        # Always recomputed; accepted on import so exported configs round-trip.
        vol.Optional("allow"): [str],
    }
)


def iter_actions(config: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield every action in keys (incl. contexts) and pages."""
    for key in config.get("keys", {}).values():
        for gesture in GESTURES:
            if gesture in key:
                yield key[gesture]
        for ctx in key.get("contexts", {}).values():
            for gesture in GESTURES:
                if gesture in ctx:
                    yield ctx[gesture]
    for page in config.get("pages", []):
        for section in page.get("sections", []):
            yield from section.get("buttons", [])
            if "action" in section:
                yield section["action"]
            for item in section.get("items", []):
                if "action" in item:
                    yield item["action"]


def _check_page_refs(config: dict[str, Any]) -> dict[str, Any]:
    ids = {p["id"] for p in config["pages"]} | {"next", "prev"}
    for action in iter_actions(config):
        if action["type"] == "page" and action["page"] not in ids:
            raise vol.Invalid(f"page action points to unknown page: {action['page']}")
    return config


def validate_config(value: Any) -> dict[str, Any]:
    """Validate a full remote config; returns a normalised copy without `allow`."""
    config = _check_page_refs(_CONFIG_SCHEMA(copy.deepcopy(value)))
    config.pop("allow", None)
    return config


def validate_pages(value: Any) -> list[dict[str, Any]]:
    """Validate a pages list."""
    return PAGES_SCHEMA(copy.deepcopy(value))


# Natural actions per domain for entities the app renders directly (tiles with an entity,
# segmented, slider, rocker, switch, now_playing). The app may call these without an
# explicit `ha` action in the config.
_ON_OFF = ("turn_on", "turn_off", "toggle")
NATURAL_ACTIONS: dict[str, tuple[str, ...]] = {
    "light": _ON_OFF,
    "switch": _ON_OFF,
    "fan": _ON_OFF,
    "input_boolean": _ON_OFF,
    "automation": _ON_OFF,
    "script": ("turn_on", "turn_off", "toggle"),
    "scene": ("turn_on",),
    "button": ("press",),
    "input_button": ("press",),
    "select": ("select_option", "select_next", "select_previous"),
    "input_select": ("select_option", "select_next", "select_previous"),
    "number": ("set_value",),
    "input_number": ("set_value",),
    "cover": ("open_cover", "close_cover", "stop_cover", "toggle", "set_cover_position"),
    "media_player": (
        "media_play_pause",
        "media_play",
        "media_pause",
        "media_stop",
        "media_next_track",
        "media_previous_track",
        "media_seek",
        "volume_set",
        "volume_up",
        "volume_down",
        "volume_mute",
        "turn_on",
        "turn_off",
    ),
}
_SECTION_NATURAL: dict[str, tuple[str, ...] | None] = {
    # None = all natural actions of the entity's domain.
    "now_playing": None,
    "segmented": None,
    "slider": None,
    "rocker": ("turn_on", "turn_off", "toggle"),
    "switch": ("turn_on", "turn_off", "toggle"),
}


def _natural(entity: str, only: tuple[str, ...] | None = None) -> Iterator[str]:
    domain = entity.split(".", 1)[0]
    for service in NATURAL_ACTIONS.get(domain, ()):
        if only is None or service in only:
            yield f"{domain}.{service}:{entity}"


def compute_allowlist(config: dict[str, Any]) -> list[str]:
    """Return the sorted allowlist: `action:entity_id`, or bare `action` when untargeted."""
    allow: set[str] = set()
    for action in iter_actions(config):
        if action["type"] != "ha":
            continue
        ids = action.get("target", {}).get("entity_id", [])
        if ids:
            allow.update(f"{action['action']}:{eid}" for eid in ids)
        else:
            allow.add(action["action"])
    for page in config.get("pages", []):
        for section in page.get("sections", []):
            typ = section["type"]
            if typ in _SECTION_NATURAL and "entity" in section:
                allow.update(_natural(section["entity"], _SECTION_NATURAL[typ]))
            if typ == "tiles":
                for item in section["items"]:
                    if "entity" in item:
                        allow.update(_natural(item["entity"]))
    return sorted(allow)


def referenced_entities(config: dict[str, Any]) -> set[str]:
    """Entities whose state is mirrored: section/tile entities, action targets, context entity."""
    found: set[str] = set()
    for action in iter_actions(config):
        if action["type"] == "ha":
            found.update(action.get("target", {}).get("entity_id", []))
    for page in config.get("pages", []):
        for section in page.get("sections", []):
            if "entity" in section:
                found.add(section["entity"])
            for item in section.get("items", []):
                if "entity" in item:
                    found.add(item["entity"])
    ctx = config.get("tv", {}).get("context_entity")
    if ctx:
        found.add(ctx)
    return found


def build_published_config(config: dict[str, Any]) -> dict[str, Any]:
    """The JSON document published to <base>/config."""
    out = copy.deepcopy(config)
    out["schema_version"] = SCHEMA_VERSION
    out["allow"] = compute_allowlist(config)
    return out


def is_call_allowed(allow: set[str], action: str, entities: list[str]) -> bool:
    """Check a call against the allowlist."""
    if not entities:
        return action in allow
    return all(f"{action}:{eid}" in allow for eid in entities)
