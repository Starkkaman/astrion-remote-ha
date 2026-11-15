"""App update entity: APKs from /config/astrion_remote/, installed via a one-time URL."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.network import NoURLAvailableError, get_url

from . import AstrionConfigEntry
from .apk import ApkRelease, ApkTokens, file_sha256, resolve_apk_dir, scan_releases
from .const import APK_VIEW_URL, DOMAIN
from .entity import AstrionEntity

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: AstrionConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add the update entity."""
    async_add_entities([AstrionUpdate(entry.runtime_data, "app")], update_before_add=True)


class AstrionUpdate(AstrionEntity, UpdateEntity):
    """Remote app update."""

    _attr_should_poll = True
    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.SPECIFIC_VERSION
    _attr_title = "Astrion Remote app"

    _releases: list[ApkRelease]

    def __init__(self, hub, key) -> None:
        super().__init__(hub, key)
        self._releases = []

    async def async_update(self) -> None:
        """Rescan the APK directory."""
        try:
            directory = resolve_apk_dir(self.hass, self.hub.apk_subdir)
        except ValueError as err:
            _LOGGER.warning("Astrion APK directory: %s", err)
            self._releases = []
        else:
            self._releases = await self.hass.async_add_executor_job(scan_releases, directory)
        self._update_from_hub()

    @callback
    def _update_from_hub(self) -> None:
        installed = self.hub.telemetry.get("app_version")
        self._attr_installed_version = installed
        self._attr_latest_version = self._releases[0].version if self._releases else installed

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        """Hand the remote a one-time URL plus sha256 over <base>/cmd."""
        if self.hub.online is False:
            raise HomeAssistantError("The remote is offline")
        await self.async_update()
        wanted = version or self._attr_latest_version
        release = next((r for r in self._releases if r.version == wanted), None)
        if release is None:
            raise HomeAssistantError(f"No APK with a valid .sha256 sidecar for version {wanted}")
        actual = await self.hass.async_add_executor_job(file_sha256, release.path)
        if actual != release.sha256:
            raise HomeAssistantError(f"{release.path.name} does not match its .sha256 sidecar")
        try:
            base_url = get_url(self.hass, prefer_external=False, allow_cloud=False)
        except NoURLAvailableError as err:
            raise HomeAssistantError("Set an internal URL in Home Assistant network settings") from err
        tokens: ApkTokens = self.hass.data[DOMAIN]["tokens"]
        token = tokens.issue(release.path)
        url = base_url + APK_VIEW_URL.format(token=token)
        await self.hub.async_send_cmd(f"update {url} {release.sha256}")
