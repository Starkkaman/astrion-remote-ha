"""Reset to defaults (service + websocket) with one-step undo, and the real upgrade path to 1.4."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.astrion_remote.const import (
    CONF_APK_DIR,
    CONF_BASE_TOPIC,
    CONF_BASE_URL,
    CONF_CONFIG,
    CONF_DEVICE_ID,
    CONF_PREVIOUS_CONFIG,
    DEFAULT_BASE_URL,
    DOMAIN,
)
from custom_components.astrion_remote.default_config import DEFAULT_CONFIG
from custom_components.astrion_remote.schema import validate_config

from .conftest import BASE

FIXTURES = Path(__file__).parent / "fixtures"
DEFAULT = validate_config(DEFAULT_CONFIG)


# ---- the upgrade path an untouched install really takes --------------------------------------
# The fixtures are the stored `config` option exactly as 0.1.0 / 0.3.0 created it: that version's
# DEFAULT_CONFIG through that version's validate_config (generated from git, then JSON like HA storage).
@pytest.mark.parametrize(
    ("fixture", "minor", "options"),
    [
        ("config_created_by_0_1_0.json", 1, {CONF_APK_DIR: ""}),
        ("config_created_by_0_3_0.json", 3, {CONF_APK_DIR: "", CONF_BASE_URL: DEFAULT_BASE_URL}),
    ],
)
async def test_untouched_install_migrates_to_new_pages(hass, mqtt_mock, fixture, minor, options):
    created = json.loads((FIXTURES / fixture).read_text())
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="ha100",
        data={CONF_DEVICE_ID: "ha100", CONF_BASE_TOPIC: BASE},
        options={CONF_CONFIG: created, **options},
        minor_version=minor,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 5
    stored = entry.options[CONF_CONFIG]
    assert stored["pages"] == DEFAULT_CONFIG["pages"]
    assert stored["keys"]["voice"] == DEFAULT_CONFIG["keys"]["voice"]
    for colour in ("red", "green", "yellow", "blue"):
        assert stored["keys"][colour]["tap"] == DEFAULT_CONFIG["keys"][colour]["tap"]
    validate_config(stored)


# ---- helpers ---------------------------------------------------------------------------------
def _published(mqtt_mock) -> list:
    return [c for c in mqtt_mock.async_publish.call_args_list if c.args[0] == f"{BASE}/config"]


async def _customise(hass, entry) -> dict:
    """Give the entry user keys and pages; return the stored config."""
    config = copy.deepcopy(entry.options[CONF_CONFIG])
    config["keys"]["sc1"] = {"tap": {"type": "tv_key", "key": "RED"}}
    config["pages"] = [{"id": "now", "title": "Mine", "sections": []}]
    config["theme"] = {"mode": "day", "calm": True}
    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_CONFIG: validate_config(config)})
    await hass.async_block_till_done()
    return copy.deepcopy(entry.options[CONF_CONFIG])


async def _send(client, payload):
    await client.send_json_auto_id(payload)
    return await client.receive_json()


# ---- services --------------------------------------------------------------------------------
async def test_service_reset_pages_only_keeps_keys_then_undo(hass, mqtt_mock, setup_entry):
    mine = await _customise(hass, setup_entry)
    before = len(_published(mqtt_mock))

    await hass.services.async_call(DOMAIN, "reset_to_defaults", {}, blocking=True)  # one entry, default parts
    await hass.async_block_till_done()
    stored = setup_entry.options[CONF_CONFIG]
    assert stored["pages"] == DEFAULT["pages"]
    assert stored["keys"] == mine["keys"]
    assert stored["theme"] == mine["theme"]
    assert setup_entry.options[CONF_PREVIOUS_CONFIG] == mine
    assert len(_published(mqtt_mock)) == before + 1
    published = json.loads(_published(mqtt_mock)[-1].args[1])
    assert [p["id"] for p in published["pages"]] == [p["id"] for p in DEFAULT["pages"]]

    await hass.services.async_call(DOMAIN, "undo_reset", {"entry_id": setup_entry.entry_id}, blocking=True)
    await hass.async_block_till_done()
    assert setup_entry.options[CONF_CONFIG] == mine
    assert CONF_PREVIOUS_CONFIG not in setup_entry.options
    assert len(_published(mqtt_mock)) == before + 2

    with pytest.raises(ServiceValidationError, match="no reset to undo"):
        await hass.services.async_call(DOMAIN, "undo_reset", {}, blocking=True)


async def test_service_reset_several_parts_keeps_only_last_backup(hass, mqtt_mock, setup_entry):
    mine = await _customise(hass, setup_entry)
    await hass.services.async_call(
        DOMAIN, "reset_to_defaults", {"parts": ["keys", "theme"]}, blocking=True
    )
    after_first = copy.deepcopy(setup_entry.options[CONF_CONFIG])
    assert after_first["keys"] == DEFAULT["keys"]
    assert after_first["theme"] == DEFAULT["theme"]
    assert after_first["pages"] == mine["pages"]
    await hass.services.async_call(DOMAIN, "reset_to_defaults", {"parts": "pages"}, blocking=True)
    assert setup_entry.options[CONF_PREVIOUS_CONFIG] == after_first  # just the last one


async def test_service_reset_rejected_cases(hass, mqtt_mock, setup_entry):
    with pytest.raises(Exception, match="parts"):
        await hass.services.async_call(DOMAIN, "reset_to_defaults", {"parts": ["allow"]}, blocking=True)
    with pytest.raises(ServiceValidationError, match="Unknown"):
        await hass.services.async_call(DOMAIN, "reset_to_defaults", {"entry_id": "nope"}, blocking=True)

    # A key that opens a page the default layout does not have: refused, nothing stored.
    config = copy.deepcopy(setup_entry.options[CONF_CONFIG])
    config["pages"].append({"id": "mine", "title": "Mine", "sections": []})
    config["keys"]["sc1"] = {"tap": {"type": "page", "page": "mine"}}
    hass.config_entries.async_update_entry(setup_entry, options={**setup_entry.options, CONF_CONFIG: config})
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError, match="invalid"):
        await hass.services.async_call(DOMAIN, "reset_to_defaults", {}, blocking=True)
    assert setup_entry.options[CONF_CONFIG] == config
    assert CONF_PREVIOUS_CONFIG not in setup_entry.options


async def test_service_needs_entry_id_with_two_remotes(hass, mqtt_mock, setup_entry):
    MockConfigEntry(
        domain=DOMAIN,
        unique_id="ha101",
        data={CONF_DEVICE_ID: "ha101", CONF_BASE_TOPIC: "astrion/ha101"},
        options={CONF_CONFIG: DEFAULT, CONF_APK_DIR: ""},
        minor_version=4,
    ).add_to_hass(hass)
    with pytest.raises(ServiceValidationError, match="entry_id"):
        await hass.services.async_call(DOMAIN, "reset_to_defaults", {}, blocking=True)
    await hass.services.async_call(
        DOMAIN, "reset_to_defaults", {"entry_id": setup_entry.entry_id}, blocking=True
    )
    assert CONF_PREVIOUS_CONFIG in setup_entry.options


# ---- websocket (what the panel's confirm dialog calls) -----------------------------------------
async def test_ws_reset_keys_and_undo(hass, mqtt_mock, setup_entry, hass_ws_client):
    mine = await _customise(hass, setup_entry)
    client = await hass_ws_client(hass)
    eid = setup_entry.entry_id

    msg = await _send(client, {"type": "astrion_remote/config/get", "entry_id": eid})
    assert msg["result"]["can_undo"] is False

    msg = await _send(client, {"type": "astrion_remote/config/reset", "entry_id": eid, "parts": ["keys"]})
    assert msg["success"], msg
    assert msg["result"]["can_undo"] is True
    assert msg["result"]["config"]["keys"] == json.loads(json.dumps(DEFAULT["keys"]))
    assert msg["result"]["config"]["pages"] == mine["pages"]
    assert setup_entry.options[CONF_CONFIG]["pages"] == mine["pages"]

    msg = await _send(client, {"type": "astrion_remote/config/get", "entry_id": eid})
    assert msg["result"]["can_undo"] is True

    msg = await _send(client, {"type": "astrion_remote/config/undo_reset", "entry_id": eid})
    assert msg["success"], msg
    assert msg["result"].pop("version")
    assert msg["result"] == {"config": json.loads(json.dumps(mine)), "can_undo": False}
    assert setup_entry.options[CONF_CONFIG] == mine

    msg = await _send(client, {"type": "astrion_remote/config/undo_reset", "entry_id": eid})
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"


async def test_ws_reset_defaults_to_pages_and_validates(hass, mqtt_mock, setup_entry, hass_ws_client):
    mine = await _customise(hass, setup_entry)
    client = await hass_ws_client(hass)
    eid = setup_entry.entry_id
    msg = await _send(client, {"type": "astrion_remote/config/reset", "entry_id": eid, "parts": ["bogus"]})
    assert not msg["success"]
    assert setup_entry.options[CONF_CONFIG] == mine
    msg = await _send(client, {"type": "astrion_remote/config/reset", "entry_id": eid})
    assert msg["success"], msg
    assert setup_entry.options[CONF_CONFIG]["pages"] == DEFAULT["pages"]
    assert setup_entry.options[CONF_CONFIG]["keys"] == mine["keys"]


async def test_ws_reset_requires_admin(hass, mqtt_mock, setup_entry, hass_ws_client, hass_read_only_access_token):
    client = await hass_ws_client(hass, hass_read_only_access_token)
    for payload in (
        {"type": "astrion_remote/config/reset", "entry_id": setup_entry.entry_id, "parts": ["pages"]},
        {"type": "astrion_remote/config/undo_reset", "entry_id": setup_entry.entry_id},
    ):
        msg = await _send(client, payload)
        assert msg["error"]["code"] == "unauthorized", payload["type"]
    assert CONF_PREVIOUS_CONFIG not in setup_entry.options


def test_panel_has_reset_controls():
    js = (Path(__file__).parents[1] / "custom_components" / DOMAIN / "frontend" / "astrion-panel.js").read_text()
    assert "Replace your pages with the current default layout? You can undo this once." in js
    assert "Reset pages to default" in js and "Reset buttons to default" in js
    assert "Undo reset" in js
    assert "/config/reset" in js and "/config/undo_reset" in js
