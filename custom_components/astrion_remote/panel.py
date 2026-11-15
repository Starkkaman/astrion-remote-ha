"""The "Astrion Remote" sidebar panel (static module + panel registration)."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    PANEL_COMPONENT,
    PANEL_ICON,
    PANEL_JS,
    PANEL_STATIC_URL,
    PANEL_TITLE,
    PANEL_URL_PATH,
)

FRONTEND_DIR = Path(__file__).parent / "frontend"


async def async_register_static(hass: HomeAssistant) -> None:
    """Serve custom_components/astrion_remote/frontend/ (once per HA run; routes cannot be removed)."""
    data = hass.data.setdefault(DOMAIN, {})
    if data.get("static_registered"):
        return
    await hass.http.async_register_static_paths(
        [StaticPathConfig(PANEL_STATIC_URL, str(FRONTEND_DIR), cache_headers=False)]
    )
    data["static_registered"] = True


async def async_register_panel(hass: HomeAssistant, version: str) -> None:
    """Add the sidebar panel if it is not there yet."""
    data = hass.data.setdefault(DOMAIN, {})
    if data.get("panel_registered"):
        return
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_COMPONENT,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=f"{PANEL_STATIC_URL}/{PANEL_JS}?v={version}",
        require_admin=True,
        config={"domain": DOMAIN},
    )
    data["panel_registered"] = True


def async_remove_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel (last remote unloaded)."""
    data = hass.data.get(DOMAIN, {})
    if data.pop("panel_registered", False):
        frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
