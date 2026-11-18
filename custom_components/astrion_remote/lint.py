"""Non-blocking lint warnings: config that validates but would do nothing on the remote.

- `ha` actions calling a service that needs a target (per HA's service description: a target
  selector or an entity_id field) without target.entity_id or data.entity_id.
- `choose` actions and choose-like sections (segmented, slider, rocker, switch) whose entity is not
  in hass.states.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.service import async_get_all_descriptions

_LOGGER = logging.getLogger(__name__)

# Used only when HA has no description for the service (integration not loaded, custom service).
_FALLBACK_TARGET_DOMAINS = ("light", "switch", "media_player", "select", "input_select")
_FALLBACK_TARGET_SERVICES = ("scene.turn_on", "script.turn_on")
_FALLBACK_NO_TARGET_SERVICES = ("reload",)

ENTITY_SECTIONS = ("segmented", "slider", "rocker", "switch")


def _has_entity_field(fields: Any) -> bool:
    if not isinstance(fields, dict):
        return False
    for name, field in fields.items():
        if name == "entity_id":
            return True
        # Collapsible field sections nest their fields one level down.
        if isinstance(field, dict) and _has_entity_field(field.get("fields")):
            return True
    return False


def service_needs_target(descriptions: dict[str, dict[str, Any]], action: str) -> bool:
    """True if `domain.service` needs a target: from HA's description, else a built-in list."""
    domain, _, service = action.partition(".")
    description = (descriptions.get(domain) or {}).get(service)
    # A service registered without a services.yaml has an empty description: use the fallback.
    if isinstance(description, dict) and (description.get("fields") or "target" in description):
        return "target" in description or _has_entity_field(description.get("fields"))
    if service in _FALLBACK_NO_TARGET_SERVICES:
        return False
    return action in _FALLBACK_TARGET_SERVICES or domain in _FALLBACK_TARGET_DOMAINS


def _has_target(action: dict[str, Any]) -> bool:
    target = action.get("target")
    if isinstance(target, dict) and target.get("entity_id"):
        return True
    data = action.get("data")
    return isinstance(data, dict) and bool(data.get("entity_id"))


def _entity_sections(config: dict[str, Any]) -> Iterator[tuple[list[Any], dict[str, Any]]]:
    pages = config.get("pages")
    for pi, page in enumerate(pages if isinstance(pages, list) else []):
        sections = page.get("sections") if isinstance(page, dict) else None
        for si, section in enumerate(sections if isinstance(sections, list) else []):
            if isinstance(section, dict) and section.get("type") in ENTITY_SECTIONS:
                yield ["pages", pi, "sections", si], section


async def async_lint(
    hass: HomeAssistant, config: Any, action_paths: Iterator[tuple[list[Any], Any]]
) -> list[dict[str, Any]]:
    """Return `[{path, msg}]` warnings; never raises (lint is a nicety)."""
    if not isinstance(config, dict):
        return []
    try:
        descriptions = await async_get_all_descriptions(hass)
    except Exception as err:  # noqa: BLE001 - fall back to the built-in list
        _LOGGER.debug("Could not load service descriptions: %s", err)
        descriptions = {}
    warnings: list[dict[str, Any]] = []
    try:
        for path, action in action_paths:
            if not isinstance(action, dict):
                continue
            if action.get("type") == "ha" and isinstance(name := action.get("action"), str):
                if not _has_target(action) and service_needs_target(descriptions, name):
                    warnings.append(
                        {"path": path, "msg": f"{name} needs a target entity; without one it does nothing"}
                    )
            elif (
                action.get("type") == "choose"
                and isinstance(ent := action.get("entity"), str)
                and hass.states.get(ent) is None
            ):
                warnings.append({"path": [*path, "entity"], "msg": f"entity {ent} does not exist"})
        for path, section in _entity_sections(config):
            ent = section.get("entity")
            if isinstance(ent, str) and hass.states.get(ent) is None:
                warnings.append(
                    {"path": [*path, "entity"], "msg": f"{section['type']}: entity {ent} does not exist"}
                )
    except (TypeError, ValueError, AttributeError) as err:
        _LOGGER.debug("Lint skipped: %s", err)
    return warnings
