"""Assist pipeline and VAD selects for the remote's assist_satellite (HA's voice UI uses them)."""

from __future__ import annotations

from homeassistant.components.assist_pipeline import (
    AssistPipelineSelect,
    VadSensitivitySelect,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AstrionConfigEntry
from .const import DOMAIN
from .hub import AstrionHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AstrionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the selects."""
    hub = entry.runtime_data
    async_add_entities([AstrionPipelineSelect(hass, hub), AstrionVadSensitivitySelect(hass, hub)])


class AstrionPipelineSelect(AssistPipelineSelect):
    """Which Assist pipeline the remote's voice key uses (unique id `<remote>-pipeline`)."""

    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, hub: AstrionHub) -> None:
        AssistPipelineSelect.__init__(self, hass, DOMAIN, hub.remote_id)
        self._attr_device_info = hub.device_info


class AstrionVadSensitivitySelect(VadSensitivitySelect):
    """How quickly HA decides the speaker has finished (unique id `<remote>-vad_sensitivity`)."""

    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, hub: AstrionHub) -> None:
        VadSensitivitySelect.__init__(self, hass, hub.remote_id)
        self._attr_device_info = hub.device_info
