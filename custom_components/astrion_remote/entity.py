"""Base entity for Astrion Remote."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .hub import AstrionHub


class AstrionEntity(Entity):
    """Entity on the "Astrion Remote" device, refreshed by the hub's dispatcher signal."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: AstrionHub, key: str) -> None:
        self.hub = hub
        self._attr_translation_key = key
        self._attr_unique_id = f"{hub.remote_id}_{key}"
        self._attr_device_info = hub.device_info

    async def async_added_to_hass(self) -> None:
        """Listen for hub updates."""
        self.async_on_remove(async_dispatcher_connect(self.hass, self.hub.signal, self._handle_update))
        self._handle_update()

    @callback
    def _handle_update(self) -> None:
        self._update_from_hub()
        if self.hass is not None and self.entity_id:
            self.async_write_ha_state()

    @callback
    def _update_from_hub(self) -> None:
        """Override to refresh attributes."""


class AstrionTelemetryEntity(AstrionEntity):
    """Entity backed by one telemetry field; unavailable while the remote is offline."""

    def __init__(self, hub: AstrionHub, key: str, field: str) -> None:
        super().__init__(hub, key)
        self._field = field

    @property
    def available(self) -> bool:
        """Available once the field was reported and the remote is not offline."""
        return self.hub.online is not False and self.hub.telemetry.get(self._field) is not None
