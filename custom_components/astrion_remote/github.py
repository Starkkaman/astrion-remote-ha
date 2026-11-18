"""App APKs from GitHub releases: listing (ETag + rate limit aware) and verified download.

Release layout (written by the app repo's scripts/release-apk.sh): tag `app-v<versionName>`, prerelease, with
assets `astrion-<versionName>-<versionCode>.apk` and `astrion-<versionName>-<versionCode>.apk.sha256`.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from http import HTTPStatus
import logging
import os
from pathlib import Path
import re
import time
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import GITHUB_API, GITHUB_PER_PAGE, MAX_APK_BYTES

_LOGGER = logging.getLogger(__name__)

APP_TAG_PREFIX = "app-v"
_ASSET_RE = re.compile(r"^astrion-(?P<name>[0-9A-Za-z][0-9A-Za-z.+_]*)-(?P<code>[0-9]{1,9})\.apk$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
_TIMEOUT = aiohttp.ClientTimeout(total=30)
_DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=600, sock_read=60)


class GithubError(Exception):
    """Listing or download failed (message is user facing)."""


@dataclass(frozen=True)
class GithubApk:
    """One app APK attached to a GitHub release."""

    name: str  # versionName
    code: int  # versionCode
    tag: str
    asset_name: str
    apk_url: str
    sha_url: str
    release_url: str | None
    notes: str | None

    @property
    def version(self) -> str:
        """Version string shown by the update entity: `<name> (<code>)`."""
        return format_version(self.name, self.code)


def format_version(name: str | None, code: int | None) -> str | None:
    """`0.4.3 (9)`, or just the name / code when the other is unknown."""
    if name and code is not None:
        return f"{name} ({code})"
    if code is not None:
        return f"({code})"
    return name


def validate_repo(value: str) -> str:
    """`owner/name` (no URL)."""
    value = (value or "").strip().strip("/")
    if not _REPO_RE.match(value) or value.split("/")[1] in (".", ".."):
        raise ValueError("invalid repository")
    return value


def parse_releases(data: Any) -> list[GithubApk]:
    """APKs from a GET /repos/{repo}/releases answer, highest versionCode first.

    Only non-draft releases tagged app-v*; prereleases count (app releases are prereleases on purpose). An APK
    needs a matching `<apk>.sha256` asset in the same release, otherwise it is skipped.
    """
    if not isinstance(data, list):
        return []
    found: dict[int, GithubApk] = {}
    for release in data:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = release.get("tag_name")
        if not isinstance(tag, str) or not tag.startswith(APP_TAG_PREFIX):
            continue
        assets = {
            a["name"]: a["browser_download_url"]
            for a in release.get("assets") or []
            if isinstance(a, dict)
            and isinstance(a.get("name"), str)
            and isinstance(a.get("browser_download_url"), str)
        }
        for asset_name, url in assets.items():
            if not (match := _ASSET_RE.match(asset_name)):
                continue
            sha_url = assets.get(asset_name + ".sha256")
            if sha_url is None:
                _LOGGER.debug("Skipping %s in %s: no %s.sha256 asset", asset_name, tag, asset_name)
                continue
            code = int(match["code"])
            if code in found:  # the same code twice: keep the first (newest release)
                continue
            found[code] = GithubApk(
                name=match["name"],
                code=code,
                tag=tag,
                asset_name=asset_name,
                apk_url=url,
                sha_url=sha_url,
                release_url=release.get("html_url") if isinstance(release.get("html_url"), str) else None,
                notes=release.get("body") if isinstance(release.get("body"), str) else None,
            )
    return [found[c] for c in sorted(found, reverse=True)]


class GithubReleases:
    """Lists one repo's releases. Unauthenticated: 60 requests/hour per IP.

    - ETag / If-None-Match: a 304 keeps the cached listing.
    - Rate limit: on 403/429 with X-RateLimit-Remaining: 0 (or Retry-After) no request is made until the
      reset time; the cached listing stays in use. A 200 with Remaining 0 also arms the wait.
    """

    def __init__(self, hass: HomeAssistant, repo: str) -> None:
        self.hass = hass
        self.repo = repo
        self.apks: list[GithubApk] = []
        self.etag: str | None = None
        self.blocked_until: float = 0.0  # wall clock (epoch seconds)
        self.last_checked: float | None = None  # monotonic time of the last good answer (200/304)
        self.last_error: str | None = None

    @property
    def url(self) -> str:
        """Listing URL."""
        return f"{GITHUB_API}/repos/{self.repo}/releases"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "astrion-remote-ha",
        }
        if self.etag:
            headers["If-None-Match"] = self.etag
        return headers

    def _arm_rate_limit(self, resp: aiohttp.ClientResponse) -> bool:
        """Remember when requests are allowed again; True if a wait is armed."""
        now = time.time()
        if retry_after := resp.headers.get("Retry-After"):
            try:
                self.blocked_until = max(self.blocked_until, now + int(retry_after))
                return True
            except ValueError:
                pass
        if resp.headers.get("X-RateLimit-Remaining") == "0":
            try:
                reset = float(resp.headers.get("X-RateLimit-Reset", ""))
            except ValueError:
                reset = now + 3600
            self.blocked_until = max(self.blocked_until, reset)
            return True
        return False

    async def async_refresh(self) -> list[GithubApk]:
        """Fetch the listing (or keep the cache on 304 / rate limit / errors)."""
        if time.time() < self.blocked_until:
            _LOGGER.debug("GitHub rate limit: next request after %s", self.blocked_until)
            return self.apks
        session = async_get_clientsession(self.hass)
        try:
            resp = await session.get(
                self.url, params={"per_page": str(GITHUB_PER_PAGE)}, headers=self._headers(), timeout=_TIMEOUT
            )
            if resp.status == HTTPStatus.NOT_MODIFIED:
                self.last_checked = time.monotonic()
                self.last_error = None
                return self.apks
            if resp.status in (HTTPStatus.FORBIDDEN, HTTPStatus.TOO_MANY_REQUESTS) and self._arm_rate_limit(resp):
                self.last_error = "GitHub rate limit reached"
                _LOGGER.warning(
                    "GitHub rate limit for %s; next check after %s",
                    self.repo,
                    time.strftime("%H:%M:%S", time.localtime(self.blocked_until)),
                )
                return self.apks
            if resp.status != HTTPStatus.OK:
                self.last_error = f"GitHub answered {resp.status}"
                _LOGGER.warning("Listing releases of %s: HTTP %s", self.repo, resp.status)
                return self.apks
            data = await resp.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            self.last_error = f"GitHub request failed: {err}"
            _LOGGER.warning("Listing releases of %s failed: %s", self.repo, err)
            return self.apks
        self._arm_rate_limit(resp)
        self.apks = parse_releases(data)
        self.etag = resp.headers.get("ETag")
        self.last_checked = time.monotonic()
        self.last_error = None
        return self.apks


def _parse_sha_file(text: str) -> str:
    digest = text.strip().split()[0].lower() if text.strip() else ""
    if not _SHA_RE.match(digest):
        raise GithubError("the .sha256 asset holds no valid sha256")
    return digest


def _write_verified(path: Path, data: bytes, digest: str, asset_name: str) -> None:
    """Write atomically (tmp + rename), plus the sha256 sidecar (blocking I/O)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    path.with_name(path.name + ".sha256").write_text(f"{digest}  {asset_name}\n", encoding="ascii")


def _cached_ok(path: Path, digest: str) -> bool:
    if not path.is_file():
        return False
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest() == digest


async def async_download(hass: HomeAssistant, apk: GithubApk, directory: Path) -> tuple[Path, str]:
    """Download the APK into `directory`, verified against its .sha256 asset. Returns (path, sha256).

    A file already there with the right hash is reused. On a mismatch nothing is kept.
    """
    session = async_get_clientsession(hass)
    try:
        resp = await session.get(apk.sha_url, timeout=_TIMEOUT)
        if resp.status != HTTPStatus.OK:
            raise GithubError(f"{apk.asset_name}.sha256: HTTP {resp.status}")
        expected = _parse_sha_file((await resp.read())[:4096].decode("ascii", errors="replace"))
        path = directory / apk.asset_name
        if await hass.async_add_executor_job(_cached_ok, path, expected):
            return path, expected
        resp = await session.get(apk.apk_url, timeout=_DOWNLOAD_TIMEOUT)
        if resp.status != HTTPStatus.OK:
            raise GithubError(f"{apk.asset_name}: HTTP {resp.status}")
        length = resp.headers.get("Content-Length", "")
        if length.isdigit() and int(length) > MAX_APK_BYTES:
            raise GithubError(f"{apk.asset_name} is larger than {MAX_APK_BYTES} bytes")
        digest = hashlib.sha256()
        buf = bytearray()
        async for chunk in resp.content.iter_chunked(1 << 16):
            buf.extend(chunk)
            if len(buf) > MAX_APK_BYTES:
                raise GithubError(f"{apk.asset_name} is larger than {MAX_APK_BYTES} bytes")
            digest.update(chunk)
    except (aiohttp.ClientError, TimeoutError) as err:
        raise GithubError(f"Downloading {apk.asset_name} failed: {err}") from err
    actual = digest.hexdigest()
    if actual != expected:
        raise GithubError(f"{apk.asset_name} does not match its .sha256 asset (got {actual[:12]}...)")
    await hass.async_add_executor_job(_write_verified, path, bytes(buf), expected, apk.asset_name)
    return path, expected
