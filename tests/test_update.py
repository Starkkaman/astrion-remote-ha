"""Update entity: APK discovery and the one-time install URL."""

import hashlib
import json
from pathlib import Path
import re
from unittest.mock import patch

import pytest

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.network import NoURLAvailableError
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_mqtt_message

from custom_components.astrion_remote.apk import ApkTokens, validate_base_url
from custom_components.astrion_remote.const import CONF_BASE_URL, DEFAULT_BASE_URL

from .conftest import BASE

ENTITY = "update.astrion_remote_app"


def _write_apk(directory: Path, version: str, content: bytes, sidecar: str | None = None) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    apk = directory / f"astrion-{version}.apk"
    apk.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    (directory / f"astrion-{version}.apk.sha256").write_text(
        (sidecar if sidecar is not None else digest) + f"  {apk.name}\n"
    )
    return digest


@pytest.fixture
def base_url_option() -> str | None:
    """base_url option on the entry; None = key missing (pre-0.1.1 entry, migrated)."""
    return None


@pytest.fixture
def config_entry(config_entry, base_url_option):
    """The shared entry, with base_url set when the test asks for it."""
    if base_url_option is None:
        return config_entry
    return MockConfigEntry(
        domain=config_entry.domain,
        title=config_entry.title,
        unique_id=config_entry.unique_id,
        data=dict(config_entry.data),
        options={**config_entry.options, CONF_BASE_URL: base_url_option},
        minor_version=2,
    )


@pytest.fixture
async def apk_setup(hass, mqtt_mock, config_entry, tmp_path):
    """Two APKs in /config/astrion_remote and the remote online at 0.1.0."""
    hass.config.config_dir = str(tmp_path)
    await async_process_ha_core_config(hass, {"internal_url": "http://192.168.5.10:8123"})
    root = tmp_path / "astrion_remote"
    _write_apk(root, "0.1.0", b"old")
    digest = _write_apk(root, "0.2.0", b"new apk bytes")
    (root / "astrion-0.3.0.apk").write_bytes(b"no sidecar, ignored")
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    async_fire_mqtt_message(hass, f"{BASE}/status", "online")
    async_fire_mqtt_message(hass, f"{BASE}/telemetry", json.dumps({"app_version": "0.1.0"}))
    await hass.async_block_till_done()
    return root, digest


async def _install_url(hass, mqtt_mock) -> str:
    mqtt_mock.async_publish.reset_mock()
    await hass.services.async_call("update", "install", {"entity_id": ENTITY}, blocking=True)
    cmds = [c.args for c in mqtt_mock.async_publish.call_args_list if c.args[0] == f"{BASE}/cmd"]
    assert len(cmds) == 1
    return cmds[0][1].split()[1]


async def test_base_url_migrated_to_default(hass, mqtt_mock, config_entry, apk_setup):
    """An entry without base_url (0.1.0) is migrated to the default option."""
    assert config_entry.minor_version == 4
    assert config_entry.options[CONF_BASE_URL] == DEFAULT_BASE_URL == "http://192.168.5.166:8123"


@pytest.mark.parametrize("base_url_option", ["http://10.0.0.7:8123/"])
async def test_update_uses_base_url_option(hass, mqtt_mock, config_entry, apk_setup):
    """The configured base_url wins over HA's internal URL (trailing slash stripped)."""
    assert config_entry.options[CONF_BASE_URL] == "http://10.0.0.7:8123/"  # kept, not overwritten
    url = await _install_url(hass, mqtt_mock)
    assert re.fullmatch(r"http://10\.0\.0\.7:8123/api/astrion_remote/apk/[\w-]+", url), url


@pytest.mark.parametrize("base_url_option", [""])
async def test_update_empty_base_url_falls_back(hass, mqtt_mock, apk_setup):
    """An empty base_url falls back to HA's internal URL."""
    url = await _install_url(hass, mqtt_mock)
    assert re.fullmatch(r"http://192\.168\.5\.10:8123/api/astrion_remote/apk/[\w-]+", url), url


@pytest.mark.parametrize("base_url_option", [""])
async def test_update_no_url_at_all(hass, mqtt_mock, apk_setup):
    """No base_url and no HA URL -> a clear error."""
    with patch(
        "custom_components.astrion_remote.update.get_url", side_effect=NoURLAvailableError
    ), pytest.raises(HomeAssistantError, match="Home Assistant URL"):
        await hass.services.async_call("update", "install", {"entity_id": ENTITY}, blocking=True)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", ""),
        ("  http://192.168.5.166:8123/ ", "http://192.168.5.166:8123"),
        ("https://ha.example.org", "https://ha.example.org"),
    ],
)
def test_validate_base_url_ok(value, expected):
    """Accepted URLs are normalized."""
    assert validate_base_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "192.168.5.166:8123",
        "ftp://host",
        "http://host:8123/ha",
        "http://host?x=1",
        "http://user:pw@host",
        "http://host:99999",
        "http://",
        "http://ho st",
    ],
)
def test_validate_base_url_rejects(value):
    """Scheme must be http(s); no path, query, credentials or bad port."""
    with pytest.raises(ValueError):
        validate_base_url(value)


async def test_update_install(hass, mqtt_mock, apk_setup, hass_client_no_auth):
    """Install publishes `update <url> <sha256>` (default base_url); the URL works once."""
    root, digest = apk_setup
    state = hass.states.get(ENTITY)
    assert state.state == STATE_ON
    assert state.attributes["installed_version"] == "0.1.0"
    assert state.attributes["latest_version"] == "0.2.0"

    mqtt_mock.async_publish.reset_mock()
    await hass.services.async_call("update", "install", {"entity_id": ENTITY}, blocking=True)
    cmds = [c.args for c in mqtt_mock.async_publish.call_args_list if c.args[0] == f"{BASE}/cmd"]
    assert len(cmds) == 1
    topic, payload, qos, retain = cmds[0]
    assert retain is False
    match = re.fullmatch(r"update (http://192\.168\.5\.166:8123(/api/astrion_remote/apk/([\w-]+))) ([0-9a-f]{64})", payload)
    assert match, payload
    assert match.group(4) == digest
    assert len(match.group(3)) >= 43  # 32 random bytes, urlsafe base64

    client = await hass_client_no_auth()
    resp = await client.get(match.group(2))
    assert resp.status == 200
    assert await resp.read() == b"new apk bytes"
    assert resp.headers["Content-Type"] == "application/vnd.android.package-archive"
    resp = await client.get(match.group(2))
    assert resp.status == 404  # one download only
    resp = await client.get("/api/astrion_remote/apk/guessed-token")
    assert resp.status == 404

    # the remote reports the new version -> no update pending
    async_fire_mqtt_message(hass, f"{BASE}/telemetry", json.dumps({"app_version": "0.2.0"}))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == STATE_OFF


async def test_update_specific_version_and_checks(hass, mqtt_mock, apk_setup):
    """Bad sidecar or offline remote refuse the install."""
    root, _ = apk_setup
    with pytest.raises(HomeAssistantError, match="no APK|No APK"):
        await hass.services.async_call(
            "update", "install", {"entity_id": ENTITY, "version": "0.3.0"}, blocking=True
        )
    (root / "astrion-0.2.0.apk").write_bytes(b"tampered")
    with pytest.raises(HomeAssistantError, match="does not match"):
        await hass.services.async_call("update", "install", {"entity_id": ENTITY}, blocking=True)

    async_fire_mqtt_message(hass, f"{BASE}/status", "offline")
    await hass.async_block_till_done()
    with pytest.raises(HomeAssistantError, match="offline"):
        await hass.services.async_call(
            "update", "install", {"entity_id": ENTITY, "version": "0.1.0"}, blocking=True
        )


def test_tokens_expire():
    """Tokens expire after the TTL and work once."""
    tokens = ApkTokens()
    with patch("custom_components.astrion_remote.apk.time.monotonic", return_value=100.0):
        token = tokens.issue(Path("/x.apk"))
    with patch("custom_components.astrion_remote.apk.time.monotonic", return_value=100.0 + 601):
        assert tokens.redeem(token) is None
    with patch("custom_components.astrion_remote.apk.time.monotonic", return_value=100.0):
        token = tokens.issue(Path("/x.apk"))
        assert tokens.redeem(token) == Path("/x.apk")
        assert tokens.redeem(token) is None
