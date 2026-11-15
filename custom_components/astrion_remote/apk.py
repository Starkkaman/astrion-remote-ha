"""APK discovery and the one-time download view used by the update entity."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from http import HTTPStatus
import logging
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urlsplit

from aiohttp import web
from awesomeversion import AwesomeVersion

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import APK_ROOT_DIRNAME, APK_TOKEN_TTL, APK_VIEW_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

_APK_RE = re.compile(r"^astrion-(?P<version>[0-9A-Za-z][0-9A-Za-z.+_-]*)\.apk$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ApkRelease:
    """One APK on disk with its expected sha256."""

    version: str
    path: Path
    sha256: str


def apk_root(hass: HomeAssistant) -> Path:
    """/config/astrion_remote."""
    return Path(hass.config.path(APK_ROOT_DIRNAME))


def resolve_apk_dir(hass: HomeAssistant, subdir: str) -> Path:
    """Resolve the configured sub directory, refusing anything outside the APK root."""
    root = apk_root(hass).resolve()
    path = (root / subdir).resolve() if subdir else root
    if path != root and root not in path.parents:
        raise ValueError(f"APK directory must be inside {root}")
    return path


def validate_subdir(value: str) -> str:
    """Validate a sub directory string from the options flow (no I/O)."""
    value = (value or "").strip().strip("/")
    if value.startswith("~") or ".." in Path(value).parts or Path(value).is_absolute():
        raise ValueError("invalid sub directory")
    return value


def validate_base_url(value: str) -> str:
    """Validate the HA base URL from the options flow: http(s)://host[:port], no path.

    Returns the normalized URL ("" means: fall back to HA's own URL).
    """
    value = (value or "").strip().rstrip("/")
    if not value:
        return ""
    try:
        parts = urlsplit(value)
        parts.port  # noqa: B018 - raises ValueError on a bad port
    except ValueError as err:
        raise ValueError("invalid URL") from err
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.path
        or parts.query
        or parts.fragment
        or parts.username
        or parts.password
        or any(c.isspace() for c in value)
    ):
        raise ValueError("invalid URL")
    return value


def _read_sidecar(apk: Path) -> str | None:
    for candidate in (apk.with_name(apk.name + ".sha256"), apk.with_suffix(".sha256")):
        if candidate.is_file():
            text = candidate.read_text(encoding="ascii", errors="replace").strip()
            digest = text.split()[0].lower() if text else ""
            if _SHA_RE.match(digest):
                return digest
            _LOGGER.warning("Ignoring %s: sidecar %s has no valid sha256", apk.name, candidate.name)
            return None
    return None


def scan_releases(directory: Path) -> list[ApkRelease]:
    """Return releases with a valid sidecar, newest first (blocking I/O)."""
    if not directory.is_dir():
        return []
    releases: list[ApkRelease] = []
    for apk in directory.iterdir():
        match = _APK_RE.match(apk.name)
        if not match or not apk.is_file():
            continue
        if (digest := _read_sidecar(apk)) is None:
            continue
        releases.append(ApkRelease(match["version"], apk, digest))
    releases.sort(key=lambda r: AwesomeVersion(r.version), reverse=True)
    return releases


def file_sha256(path: Path) -> str:
    """sha256 of a file (blocking I/O)."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class _Grant:
    path: Path
    expires: float


class ApkTokens:
    """One-time, expiring download grants. A single view serves all of them.

    HA cannot unregister HTTP views, so instead of one view per install there is one view
    whose path carries a random 32-byte token that works once and for 10 minutes.
    """

    def __init__(self) -> None:
        self._grants: dict[str, _Grant] = {}

    def issue(self, path: Path, ttl: float = APK_TOKEN_TTL) -> str:
        """Create a token for a file."""
        self._purge()
        token = secrets.token_urlsafe(32)
        self._grants[token] = _Grant(path, time.monotonic() + ttl)
        return token

    def redeem(self, token: str) -> Path | None:
        """Consume a token; returns the file or None."""
        self._purge()
        for known in list(self._grants):
            if secrets.compare_digest(known, token):
                return self._grants.pop(known).path
        return None

    def _purge(self) -> None:
        now = time.monotonic()
        for token in [t for t, g in self._grants.items() if g.expires <= now]:
            del self._grants[token]

    def __len__(self) -> int:
        self._purge()
        return len(self._grants)


class ApkDownloadView(HomeAssistantView):
    """Serves an APK once per token, without HA auth (the remote has no HA token)."""

    url = APK_VIEW_URL
    name = f"api:{DOMAIN}:apk"
    requires_auth = False

    def __init__(self, tokens: ApkTokens) -> None:
        self._tokens = tokens

    async def get(self, request: web.Request, token: str) -> web.StreamResponse:
        """Serve the file for a valid token."""
        path = self._tokens.redeem(token)
        if path is None:
            return web.Response(status=HTTPStatus.NOT_FOUND)
        return web.FileResponse(
            path,
            headers={
                "Content-Type": "application/vnd.android.package-archive",
                "Content-Disposition": f'attachment; filename="{path.name}"',
                "Cache-Control": "no-store",
            },
        )
