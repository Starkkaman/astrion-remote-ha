"""Reload-config and go-home buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AstrionConfigEntry
from .entity import AstrionEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: AstrionConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add buttons."""
    hub = entry.runtime_data
    async_add_entities([AstrionReloadButton(hub, "reload_config"), AstrionHomeButton(hub, "home_page")])


class AstrionReloadButton(AstrionEntity, ButtonEntity):
    """Re-publish the config and tell the app to reload."""

    async def async_press(self) -> None:
        """Press."""
        await self.hub.async_publish_config()
        await self.hub.async_send_cmd("reload")


class AstrionHomeButton(AstrionEntity, ButtonEntity):
    """Show the first page."""

    async def async_press(self) -> None:
        """Press."""
        await self.hub.async_send_cmd(f"page {self.hub.home_page}")
