"""App updates from GitHub releases: listing, ETag / rate limit, verified download, auto-install, options."""

import hashlib
import json
import re
import time

import pytest

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_mqtt_message

from custom_components.astrion_remote.const import (
    CONF_APK_DIR,
    CONF_AUTO_INSTALL,
    CONF_BASE_URL,
    CONF_CONFIG,
    CONF_GITHUB_REPO,
    CONF_UPDATE_SOURCE,
)
from custom_components.astrion_remote.github import (
    GithubApk,
    GithubError,
    GithubReleases,
    async_download,
    parse_releases,
    validate_repo,
)

from .conftest import BASE, GITHUB_RE

ENTITY = "update.astrion_remote_app"
REPO = "Starkkaman/astrion-remote-ha"
LIST_URL = f"https://api.github.com/repos/{REPO}/releases"
DL = f"https://github.com/{REPO}/releases/download"
APK_BYTES = b"signed apk 0.4.3"
APK_SHA = hashlib.sha256(APK_BYTES).hexdigest()


def _asset(tag: str, name: str) -> dict:
    return {"name": name, "browser_download_url": f"{DL}/{tag}/{name}"}


def _release(tag: str, *names: str, prerelease: bool = True, draft: bool = False, body: str = "") -> dict:
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "html_url": f"https://github.com/{REPO}/releases/tag/{tag}",
        "body": body,
        "assets": [_asset(tag, n) for n in names],
    }


def _listing() -> list[dict]:
    return [
        _release("v0.5.0", "astrion-9.9.9-99.apk", "astrion-9.9.9-99.apk.sha256", prerelease=False),  # not app-v*
        _release("app-v0.4.4", "astrion-0.4.4-10.apk"),  # no .sha256 -> skipped
        _release("app-v0.5.0", "astrion-0.5.0-11.apk", "astrion-0.5.0-11.apk.sha256", draft=True),  # draft
        _release("app-v0.4.3", "astrion-0.4.3-9.apk", "astrion-0.4.3-9.apk.sha256", body="Fixes things"),
        _release("app-v0.4.2", "astrion-0.4.2-8.apk", "astrion-0.4.2-8.apk.sha256", prerelease=False),
        _release("app-vbad", "astrion-x.apk", "astrion-x.apk.sha256", "notes.txt"),  # no code in the name
    ]


def test_parse_releases():
    """app-v* only (prereleases count), drafts and APKs without .sha256 skipped, highest code first."""
    apks = parse_releases(_listing())
    assert [(a.name, a.code, a.tag) for a in apks] == [("0.4.3", 9, "app-v0.4.3"), ("0.4.2", 8, "app-v0.4.2")]
    top = apks[0]
    assert top.version == "0.4.3 (9)"
    assert top.apk_url == f"{DL}/app-v0.4.3/astrion-0.4.3-9.apk"
    assert top.sha_url == f"{DL}/app-v0.4.3/astrion-0.4.3-9.apk.sha256"
    assert top.release_url.endswith("/tag/app-v0.4.3")
    assert top.notes == "Fixes things"
    assert parse_releases({"message": "Not Found"}) == []
    assert parse_releases([None, {"tag_name": 5}]) == []


@pytest.mark.parametrize("value", ["", "owner", "https://github.com/a/b", "a/b/c", "a b/c", "a/.."])
def test_validate_repo_rejects(value):
    """owner/name only."""
    with pytest.raises(ValueError):
        validate_repo(value)


def test_validate_repo_ok():
    """Whitespace and slashes around are trimmed."""
    assert validate_repo(" /Starkkaman/astrion-remote-ha/ ") == REPO


async def test_etag_and_rate_limit(hass, github_api):
    """200 stores the ETag; 304 keeps the cache; a 403 with Remaining 0 stops requests until the reset."""
    client = GithubReleases(hass, REPO)
    github_api.clear_requests()
    github_api.get(LIST_URL, json=_listing(), headers={"ETag": '"v1"', "X-RateLimit-Remaining": "59"})
    assert [a.code for a in await client.async_refresh()] == [9, 8]
    _method, url, _, headers = github_api.mock_calls[-1]
    assert url.query["per_page"] == "20"
    assert "If-None-Match" not in headers
    assert client.etag == '"v1"'

    github_api.clear_requests()
    github_api.get(LIST_URL, status=304)
    assert [a.code for a in await client.async_refresh()] == [9, 8]  # cache kept
    assert github_api.mock_calls[-1][3]["If-None-Match"] == '"v1"'

    github_api.clear_requests()
    reset = int(time.time()) + 3600
    github_api.get(
        LIST_URL, status=403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset)}
    )
    assert [a.code for a in await client.async_refresh()] == [9, 8]
    assert client.blocked_until == reset
    assert client.last_error == "GitHub rate limit reached"
    calls = github_api.call_count
    assert [a.code for a in await client.async_refresh()] == [9, 8]
    assert github_api.call_count == calls  # no request while blocked

    # after the reset: requests again (Retry-After on a 429 also arms the wait)
    client.blocked_until = 0
    github_api.clear_requests()
    github_api.get(LIST_URL, status=429, headers={"Retry-After": "120"})
    await client.async_refresh()
    assert 110 < client.blocked_until - time.time() <= 120

    # a plain error keeps the cache too
    client.blocked_until = 0
    github_api.clear_requests()
    github_api.get(LIST_URL, status=500)
    assert [a.code for a in await client.async_refresh()] == [9, 8]
    assert client.last_error == "GitHub answered 500"


def _apk(tag: str = "app-v0.4.3", name: str = "astrion-0.4.3-9.apk") -> GithubApk:
    return GithubApk("0.4.3", 9, tag, name, f"{DL}/{tag}/{name}", f"{DL}/{tag}/{name}.sha256", None, None)


async def test_download_verifies_sha256(hass, github_api, tmp_path):
    """A mismatch is rejected and nothing is kept; a match is written with its sidecar and reused."""
    apk = _apk()
    github_api.clear_requests()
    github_api.get(apk.sha_url, text=f"{hashlib.sha256(b'other').hexdigest()}  {apk.asset_name}\n")
    github_api.get(apk.apk_url, text=APK_BYTES.decode())
    target = tmp_path / "astrion_remote"
    with pytest.raises(GithubError, match="does not match"):
        await async_download(hass, apk, target)
    assert not target.exists() or list(target.iterdir()) == []

    github_api.clear_requests()
    github_api.get(apk.sha_url, text=f"{APK_SHA}  {apk.asset_name}\n")
    github_api.get(apk.apk_url, text=APK_BYTES.decode())
    path, digest = await async_download(hass, apk, target)
    assert digest == APK_SHA
    assert path == target / "astrion-0.4.3-9.apk"
    assert path.read_bytes() == APK_BYTES
    assert (target / "astrion-0.4.3-9.apk.sha256").read_text().split()[0] == APK_SHA
    calls = github_api.call_count
    await async_download(hass, apk, target)
    assert github_api.call_count == calls + 1  # only the .sha256 again; the verified file is reused

    github_api.clear_requests()
    github_api.get(apk.sha_url, text="not a hash")
    with pytest.raises(GithubError, match="no valid sha256"):
        await async_download(hass, apk, tmp_path / "other")


def _mock_release(github_api, apk_bytes: bytes = APK_BYTES, sha: str = APK_SHA) -> None:
    github_api.clear_requests()
    github_api.get(LIST_URL, json=_listing(), headers={"ETag": '"v1"'})
    github_api.get(f"{DL}/app-v0.4.3/astrion-0.4.3-9.apk.sha256", text=f"{sha}  astrion-0.4.3-9.apk\n")
    github_api.get(f"{DL}/app-v0.4.3/astrion-0.4.3-9.apk", text=apk_bytes.decode())
    github_api.get(GITHUB_RE, json=[])


async def _setup(hass, mqtt_mock, tmp_path, options: dict | None = None, online: bool = True):
    hass.config.config_dir = str(tmp_path)
    await async_process_ha_core_config(hass, {"internal_url": "http://192.168.5.10:8123"})
    entry = MockConfigEntry(
        domain="astrion_remote",
        title="Astrion Remote (ha100)",
        unique_id="ha100",
        data={"device_id": "ha100", "base_topic": BASE},
        options={CONF_APK_DIR: "", **(options or {})},
        minor_version=5,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    if online:
        async_fire_mqtt_message(hass, f"{BASE}/status", "online")
    async_fire_mqtt_message(hass, f"{BASE}/telemetry", json.dumps({"version": "0.4.2", "version_code": 8}))
    await hass.async_block_till_done()
    return entry


def _cmds(mqtt_mock) -> list[str]:
    return [c.args[1] for c in mqtt_mock.async_publish.call_args_list if c.args[0] == f"{BASE}/cmd"]


async def test_github_install(hass, mqtt_mock, github_api, tmp_path, hass_client_no_auth):
    """Latest app release by versionCode; install downloads, verifies and sends `update <url> <sha>`."""
    _mock_release(github_api)
    await _setup(hass, mqtt_mock, tmp_path)
    state = hass.states.get(ENTITY)
    assert state.state == STATE_ON
    assert state.attributes["installed_version"] == "0.4.2 (8)"
    assert state.attributes["latest_version"] == "0.4.3 (9)"
    assert state.attributes["release_url"].endswith("/tag/app-v0.4.3")
    assert state.attributes["in_progress"] is False

    mqtt_mock.async_publish.reset_mock()
    await hass.services.async_call("update", "install", {"entity_id": ENTITY}, blocking=True)
    cmds = _cmds(mqtt_mock)
    assert len(cmds) == 1
    match = re.fullmatch(r"update http://192\.168\.5\.10:8123(/api/astrion_remote/apk/[\w-]+) ([0-9a-f]{64})", cmds[0])
    assert match, cmds[0]
    assert match.group(2) == APK_SHA
    assert (tmp_path / "astrion_remote" / "astrion-0.4.3-9.apk").read_bytes() == APK_BYTES
    client = await hass_client_no_auth()
    resp = await client.get(match.group(1))
    assert resp.status == 200
    assert await resp.read() == APK_BYTES

    # the remote reports progress, then the new version
    async_fire_mqtt_message(hass, f"{BASE}/telemetry", json.dumps({"update_state": "installing"}))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes["in_progress"] is True
    async_fire_mqtt_message(
        hass, f"{BASE}/telemetry", json.dumps({"version": "0.4.3", "version_code": 9, "update_state": "idle"})
    )
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state.state == STATE_OFF
    assert state.attributes["in_progress"] is False

    # release notes come from the release body
    entity = hass.data["entity_components"]["update"].get_entity(ENTITY)
    assert await entity.async_release_notes() == "Fixes things"


async def test_github_install_sha_mismatch(hass, mqtt_mock, github_api, tmp_path):
    """A tampered download is refused; nothing is sent to the remote."""
    _mock_release(github_api, apk_bytes=b"tampered")
    await _setup(hass, mqtt_mock, tmp_path)
    mqtt_mock.async_publish.reset_mock()
    with pytest.raises(HomeAssistantError, match="does not match"):
        await hass.services.async_call("update", "install", {"entity_id": ENTITY}, blocking=True)
    assert _cmds(mqtt_mock) == []
    assert not (tmp_path / "astrion_remote" / "astrion-0.4.3-9.apk").exists()
    assert hass.states.get(ENTITY).attributes["in_progress"] is False


async def test_github_specific_version(hass, mqtt_mock, github_api, tmp_path):
    """An unknown version is refused with a clear message."""
    _mock_release(github_api)
    await _setup(hass, mqtt_mock, tmp_path)
    with pytest.raises(HomeAssistantError, match="No app release"):
        await hass.services.async_call(
            "update", "install", {"entity_id": ENTITY, "version": "0.9.9 (99)"}, blocking=True
        )


async def test_auto_install(hass, mqtt_mock, github_api, tmp_path):
    """auto_install: a newer release is sent once the remote is online, and only once per versionCode."""
    _mock_release(github_api)
    mqtt_mock.async_publish.reset_mock()
    await _setup(hass, mqtt_mock, tmp_path, {CONF_AUTO_INSTALL: True}, online=False)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert _cmds(mqtt_mock) == []  # status unknown -> waits

    async_fire_mqtt_message(hass, f"{BASE}/status", "online")
    await hass.async_block_till_done(wait_background_tasks=True)  # auto-install runs as a background task
    cmds = _cmds(mqtt_mock)
    assert len(cmds) == 1 and cmds[0].startswith("update ") and cmds[0].endswith(APK_SHA)

    # more telemetry (still the old version, e.g. the remote refused it): no retry loop
    async_fire_mqtt_message(hass, f"{BASE}/telemetry", json.dumps({"version_code": 8, "update_state": "failed"}))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(_cmds(mqtt_mock)) == 1


async def test_no_auto_install_by_default(hass, mqtt_mock, github_api, tmp_path):
    """Default: only shows the update."""
    _mock_release(github_api)
    mqtt_mock.async_publish.reset_mock()
    await _setup(hass, mqtt_mock, tmp_path)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(ENTITY).state == STATE_ON
    assert _cmds(mqtt_mock) == []


async def test_github_listing_on_demand(hass, mqtt_mock, github_api, tmp_path):
    """homeassistant.update_entity lists again (conditional request with the stored ETag)."""
    _mock_release(github_api)
    await _setup(hass, mqtt_mock, tmp_path)
    before = github_api.call_count
    await hass.services.async_call("homeassistant", "update_entity", {"entity_id": ENTITY}, blocking=True)
    assert github_api.call_count == before + 1
    assert github_api.mock_calls[-1][3]["If-None-Match"] == '"v1"'


async def test_migration_keeps_options(hass, mqtt_mock):
    """1.4 -> 1.5 adds the update options with their defaults and keeps every existing option."""
    from custom_components.astrion_remote.default_config import DEFAULT_CONFIG
    from custom_components.astrion_remote.schema import validate_config

    config = validate_config(DEFAULT_CONFIG)
    config["theme"] = {"mode": "night", "calm": True}
    old = {CONF_CONFIG: config, CONF_APK_DIR: "apks", CONF_BASE_URL: "http://10.0.0.7:8123"}
    entry = MockConfigEntry(
        domain="astrion_remote",
        unique_id="ha100",
        data={"device_id": "ha100", "base_topic": BASE},
        options=old,
        minor_version=4,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 5
    assert {k: entry.options[k] for k in old} == old
    assert entry.options[CONF_UPDATE_SOURCE] == "github"
    assert entry.options[CONF_GITHUB_REPO] == REPO
    assert entry.options[CONF_AUTO_INSTALL] is False


async def test_options_update_fields(hass, mqtt_mock, setup_entry):
    """The update options live in Timings & theme; the repo is validated."""
    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "timings"})
    user = {
        "hold_ms": 450,
        "double_ms": 350,
        "keepalive_ms": 300,
        "theme_mode": "auto",
        "calm": False,
        "keytopic": "controlfreak/hisense_tv/key/set",
        CONF_UPDATE_SOURCE: "folder",
        CONF_GITHUB_REPO: "not a repo",
        CONF_AUTO_INSTALL: True,
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], user)
    assert result["errors"] == {CONF_GITHUB_REPO: "invalid_github_repo"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**user, CONF_GITHUB_REPO: "someone/fork"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert setup_entry.options[CONF_UPDATE_SOURCE] == "folder"
    assert setup_entry.options[CONF_GITHUB_REPO] == "someone/fork"
    assert setup_entry.options[CONF_AUTO_INSTALL] is True
    assert setup_entry.runtime_data.update_source == "folder"


async def test_github_polls_every_6_hours(hass, mqtt_mock, github_api, tmp_path):
    """The 5-minute tick only lists GitHub again once 6 hours have passed since the last attempt."""
    from datetime import timedelta
    from unittest.mock import patch

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    _mock_release(github_api)
    await _setup(hass, mqtt_mock, tmp_path)
    before = github_api.call_count
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done()
    assert github_api.call_count == before, [str(c[1]) for c in github_api.mock_calls]
    later = time.monotonic() + 6 * 3600 + 1
    with patch("custom_components.astrion_remote.update.time.monotonic", return_value=later):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=12))
        await hass.async_block_till_done()
    assert github_api.call_count == before + 1
