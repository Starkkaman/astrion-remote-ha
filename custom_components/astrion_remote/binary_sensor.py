"""Charging, screen, picked-up, stock-suspended and connectivity binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AstrionConfigEntry
from .entity import AstrionEntity, AstrionTelemetryEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: AstrionConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add binary sensors."""
    hub = entry.runtime_data
    async_add_entities(
        [
            AstrionTelemetryBinary(hub, "charging", "charging", BinarySensorDeviceClass.BATTERY_CHARGING),
            AstrionTelemetryBinary(hub, "screen", "screen", None),
            AstrionTelemetryBinary(hub, "picked_up", "picked_up", BinarySensorDeviceClass.MOVING),
            AstrionTelemetryBinary(
                hub, "stock_suspended", "stock_suspended", None, category=EntityCategory.DIAGNOSTIC
            ),
            AstrionConnectivity(hub, "connectivity"),
        ]
    )


class AstrionTelemetryBinary(AstrionTelemetryEntity, BinarySensorEntity):
    """Boolean telemetry value."""

    def __init__(self, hub, key, field, device_class, *, category=None) -> None:
        super().__init__(hub, key, field)
        self._attr_device_class = device_class
        self._attr_entity_category = category

    @callback
    def _update_from_hub(self) -> None:
        self._attr_is_on = self.hub.telemetry.get(self._field)


class AstrionConnectivity(AstrionEntity, BinarySensorEntity):
    """Online/offline from <base>/status (LWT)."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @callback
    def _update_from_hub(self) -> None:
        self._attr_is_on = self.hub.online
