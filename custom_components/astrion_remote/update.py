"""App update entity: APKs from GitHub releases or /config/astrion_remote/, installed via a one-time URL.

Sources (option `update_source`):
- github (default): `app-v*` releases of `github_repo`, listed every 6 hours and on demand
  (homeassistant.update_entity); versions compare by versionCode. The APK is downloaded to /config/astrion_remote/,
  checked against its .sha256 asset, then handed to the remote like a folder APK. Optional auto-install.
- folder: astrion-<version>.apk + .sha256 sidecar in the APK directory, rescanned every 5 minutes.
Either way the remote gets `update <one-time url> <sha256>` on <base>/cmd and verifies hash, signer and versionCode.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from pathlib import Path
import re
import time
from typing import Any

from awesomeversion import AwesomeVersion

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.network import NoURLAvailableError, get_url

from . import AstrionConfigEntry
from .apk import ApkRelease, ApkTokens, apk_root, file_sha256, resolve_apk_dir, scan_releases
from .const import APK_VIEW_URL, DOMAIN, GITHUB_POLL_HOURS, UPDATE_SOURCE_FOLDER, UPDATE_SOURCE_GITHUB
from .entity import AstrionEntity
from .github import GithubApk, GithubError, GithubReleases, async_download, format_version

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1
TICK = timedelta(minutes=5)  # folder rescan; GitHub checks when due
GITHUB_POLL = timedelta(hours=GITHUB_POLL_HOURS)
GITHUB_RETRY = timedelta(minutes=30)  # after a failed listing (not the rate limit, that has its own wait)
REMOTE_BUSY = ("downloading", "verifying", "installing")  # telemetry update_state while the app updates

_CODE_RE = re.compile(r"\((\d+)\)$")


def _code_of(version: str) -> int | None:
    match = _CODE_RE.search(version.strip())
    return int(match.group(1)) if match else None


def _name_of(version: str) -> str:
    return _CODE_RE.sub("", version).strip()


async def async_setup_entry(
    hass: HomeAssistant, entry: AstrionConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add the update entity."""
    async_add_entities([AstrionUpdate(entry.runtime_data, "app")], update_before_add=True)


class AstrionUpdate(AstrionEntity, UpdateEntity):
    """Remote app update."""

    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.SPECIFIC_VERSION
        | UpdateEntityFeature.PROGRESS
        | UpdateEntityFeature.RELEASE_NOTES
    )
    _attr_title = "Astrion Remote app"

    def __init__(self, hub, key) -> None:
        super().__init__(hub, key)
        self._releases: list[ApkRelease] = []
        self._github: GithubReleases | None = None
        self._github_attempt: float | None = None  # monotonic time of the last listing attempt
        self._installing = False
        self._auto_tried: set[int] = set()  # versionCodes auto-install already sent (no retry loop)
        self._ready = False
        self._seen_source: tuple[str, str] | None = None

    # ---- sources ---------------------------------------------------------------------------------
    @property
    def _source(self) -> str:
        return self.hub.update_source

    def _client(self) -> GithubReleases:
        """GitHub client for the configured repo (a new repo starts with an empty cache)."""
        if self._github is None or self._github.repo != self.hub.github_repo:
            self._github = GithubReleases(self.hass, self.hub.github_repo)
            self._github_attempt = None
        return self._github

    @property
    def _apks(self) -> list[GithubApk]:
        return self._github.apks if self._github is not None and self._source == UPDATE_SOURCE_GITHUB else []

    async def _async_refresh_github(self) -> None:
        client = self._client()  # may reset the attempt time (new repo): take it first
        self._github_attempt = time.monotonic()
        await client.async_refresh()

    def _github_due(self) -> bool:
        if self._github_attempt is None or self._github is None or self._github.repo != self.hub.github_repo:
            return True
        wait = GITHUB_POLL if self._github.last_error is None else GITHUB_RETRY
        return time.monotonic() - self._github_attempt >= wait.total_seconds()

    async def async_added_to_hass(self) -> None:
        """Start the 5-minute tick (folder rescan, GitHub when due)."""
        await super().async_added_to_hass()
        self.async_on_remove(async_track_time_interval(self.hass, self._async_tick, TICK))
        self._ready = True
        self._maybe_auto_install()

    async def _async_tick(self, _now: datetime) -> None:
        if self._source == UPDATE_SOURCE_FOLDER:
            await self.async_update()
        elif self._github_due():
            await self._async_refresh_github()
            self._update_from_hub()
        else:
            return
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """On demand (and before add): rescan the folder or list the GitHub releases."""
        if self._source == UPDATE_SOURCE_GITHUB:
            await self._async_refresh_github()
        else:
            try:
                directory = resolve_apk_dir(self.hass, self.hub.apk_subdir)
            except ValueError as err:
                _LOGGER.warning("Astrion APK directory: %s", err)
                self._releases = []
            else:
                self._releases = await self.hass.async_add_executor_job(scan_releases, directory)
        self._update_from_hub()

    # ---- state -----------------------------------------------------------------------------------
    @callback
    def _update_from_hub(self) -> None:
        telemetry = self.hub.telemetry
        if self._source == UPDATE_SOURCE_GITHUB:
            installed = format_version(telemetry.get("app_version"), telemetry.get("version_code"))
            apks = self._apks
            self._attr_installed_version = installed
            self._attr_latest_version = apks[0].version if apks else installed
            self._attr_release_url = apks[0].release_url if apks else None
        else:
            installed = telemetry.get("app_version")
            self._attr_installed_version = installed
            self._attr_latest_version = self._releases[0].version if self._releases else installed
            self._attr_release_url = None
        # Source or repo changed in the options: list the new source now.
        current = (self._source, self.hub.github_repo)
        if self._ready and self._seen_source is not None and current != self._seen_source:
            self.hass.async_create_task(self._async_resync(), eager_start=False)
        self._seen_source = current
        self._maybe_auto_install()

    async def _async_resync(self) -> None:
        await self.async_update()
        self.async_write_ha_state()

    @property
    def in_progress(self) -> bool:
        """True while HA downloads/sends the APK or the remote reports it is updating."""
        return self._installing or self.hub.telemetry.get("update_state") in REMOTE_BUSY

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        """Compare versionCodes when both are known (`name (code)`), else the names."""
        latest_code, installed_code = _code_of(latest_version), _code_of(installed_version)
        if latest_code is not None and installed_code is not None:
            return latest_code > installed_code
        return AwesomeVersion(_name_of(latest_version)) > AwesomeVersion(_name_of(installed_version))

    async def async_release_notes(self) -> str | None:
        """Body of the latest GitHub release."""
        apks = self._apks
        return apks[0].notes if apks else None

    # ---- install ---------------------------------------------------------------------------------
    def _pick(self, version: str | None) -> GithubApk | None:
        apks = self._apks
        if not apks:
            return None
        if version is None:
            return apks[0]
        wanted = version.strip()
        for apk in apks:
            if wanted in (apk.version, apk.name, str(apk.code)) or _code_of(wanted) == apk.code:
                return apk
        return None

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        """Hand the remote a one-time URL plus sha256 over <base>/cmd."""
        if self.hub.online is False:
            raise HomeAssistantError("The remote is offline")
        if self._installing:
            raise HomeAssistantError("An app update is already being sent")
        if self._source == UPDATE_SOURCE_GITHUB:
            if (apk := self._pick(version)) is None:
                await self._async_refresh_github()
                self._update_from_hub()
                apk = self._pick(version)
            if apk is None:
                raise HomeAssistantError(
                    f"No app release with an APK and a .sha256 asset for {version or 'the latest version'} "
                    f"on {self.hub.github_repo}"
                )
            await self._async_install_github(apk)
            return
        await self._async_install_folder(version)

    async def _async_install_folder(self, version: str | None) -> None:
        await self.async_update()
        wanted = version or self._attr_latest_version
        release = next((r for r in self._releases if r.version == wanted), None)
        if release is None:
            raise HomeAssistantError(f"No APK with a valid .sha256 sidecar for version {wanted}")
        self._set_installing(True)
        try:
            actual = await self.hass.async_add_executor_job(file_sha256, release.path)
            if actual != release.sha256:
                raise HomeAssistantError(f"{release.path.name} does not match its .sha256 sidecar")
            await self._async_send_update(release.path, release.sha256)
        finally:
            self._set_installing(False)

    async def _async_install_github(self, apk: GithubApk) -> None:
        self._set_installing(True)
        try:
            try:
                path, digest = await async_download_apk(self.hass, apk)
            except GithubError as err:
                raise HomeAssistantError(str(err)) from err
            await self._async_send_update(path, digest)
        finally:
            self._set_installing(False)

    @callback
    def _set_installing(self, value: bool) -> None:
        self._installing = value
        if self.hass is not None and self.entity_id:
            self.async_write_ha_state()

    async def _async_send_update(self, path: Path, sha256: str) -> None:
        """Issue a one-time URL for `path` and send `update <url> <sha256>` (unchanged wire format)."""
        base_url = self.hub.base_url
        if not base_url:
            try:
                base_url = get_url(self.hass, prefer_external=False, allow_cloud=False)
            except NoURLAvailableError as err:
                raise HomeAssistantError(
                    "Set the Home Assistant URL in the Astrion options (Timings & theme)"
                ) from err
        tokens: ApkTokens = self.hass.data[DOMAIN]["tokens"]
        token = tokens.issue(path)
        url = base_url + APK_VIEW_URL.format(token=token)
        await self.hub.async_send_cmd(f"update {url} {sha256}")

    # ---- auto-install ----------------------------------------------------------------------------
    @callback
    def _maybe_auto_install(self) -> None:
        """Newer GitHub APK + auto_install + remote online and idle: install it (once per versionCode)."""
        if not self._ready or self._source != UPDATE_SOURCE_GITHUB or not self.hub.auto_install:
            return
        if self.hub.online is not True or self.in_progress:
            return
        apks = self._apks
        installed_code = self.hub.telemetry.get("version_code")
        if not apks or not isinstance(installed_code, int):
            return  # an app too old to report version_code is updated by hand
        apk = apks[0]
        if apk.code <= installed_code or apk.code in self._auto_tried:
            return
        self._auto_tried.add(apk.code)
        _LOGGER.info("Auto-installing Astrion app %s (installed code %s)", apk.version, installed_code)
        self.hass.async_create_background_task(self._async_auto_install(apk), f"{DOMAIN} auto-install")

    async def _async_auto_install(self, apk: GithubApk) -> None:
        try:
            await self._async_install_github(apk)
        except HomeAssistantError as err:
            _LOGGER.warning("Auto-install of Astrion app %s failed: %s", apk.version, err)


async def async_download_apk(hass: HomeAssistant, apk: GithubApk) -> tuple[Path, str]:
    """Download into /config/astrion_remote/ (created if missing); verified against the .sha256 asset."""
    return await async_download(hass, apk, apk_root(hass))
