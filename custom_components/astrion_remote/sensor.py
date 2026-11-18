"""Telemetry sensors."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AstrionConfigEntry
from .const import KIOSK_STATES
from .entity import AstrionTelemetryEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: AstrionConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add sensors."""
    hub = entry.runtime_data
    async_add_entities(
        [
            AstrionSensor(
                hub,
                "battery",
                "battery",
                device_class=SensorDeviceClass.BATTERY,
                unit=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
            ),
            AstrionSensor(hub, "page", "page"),
            AstrionSensor(hub, "app_version", "app_version", category=EntityCategory.DIAGNOSTIC),
            AstrionSensor(
                hub,
                "wifi_rssi",
                "wifi_rssi",
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                unit=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
                state_class=SensorStateClass.MEASUREMENT,
                category=EntityCategory.DIAGNOSTIC,
            ),
            AstrionSensor(hub, "last_key", "last_key"),
            AstrionSensor(
                hub,
                "kiosk",
                "kiosk",
                device_class=SensorDeviceClass.ENUM,
                options=list(KIOSK_STATES),
                category=EntityCategory.DIAGNOSTIC,
            ),
        ]
    )


class AstrionSensor(AstrionTelemetryEntity, SensorEntity):
    """A telemetry value."""

    def __init__(
        self, hub, key, field, *, device_class=None, unit=None, state_class=None, category=None, options=None
    ):
        super().__init__(hub, key, field)
        if options is not None:
            self._attr_options = options
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class
        self._attr_entity_category = category

    @callback
    def _update_from_hub(self) -> None:
        self._attr_native_value = self.hub.telemetry.get(self._field)
