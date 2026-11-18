"""Websocket API and sidebar panel of the visual editor."""

import copy
import json

from homeassistant.components.frontend import DATA_PANELS

from custom_components.astrion_remote.const import CONF_CONFIG, KEY_IDS, TV_KEYS

from .conftest import BASE


def _published(mqtt_mock):
    calls = [c for c in mqtt_mock.async_publish.call_args_list if c.args[0] == f"{BASE}/config"]
    return calls


async def _send(client, payload):
    await client.send_json_auto_id(payload)
    return await client.receive_json()


async def test_get_returns_config_keys_and_contexts(hass, mqtt_mock, setup_entry, hass_ws_client):
    """config/get: stored config, schema version, every key with label+group, context values."""
    config = copy.deepcopy(setup_entry.options[CONF_CONFIG])
    config["keys"]["red"]["contexts"] = {"com.netflix": {"tap": {"type": "tv_key", "key": "INFO"}}} | config[
        "keys"
    ]["red"].get("contexts", {})
    hass.config_entries.async_update_entry(setup_entry, options={**setup_entry.options, CONF_CONFIG: config})
    await hass.async_block_till_done()
    hass.states.async_set("sensor.hisense_tv_current_app", "com.youtube")

    client = await hass_ws_client(hass)
    msg = await _send(client, {"type": "astrion_remote/config/get", "entry_id": setup_entry.entry_id})
    assert msg["success"], msg
    result = msg["result"]
    assert result["schema_version"] == 1
    assert result["config"] == json.loads(json.dumps(config))
    assert [k["id"] for k in result["keys"]] == list(KEY_IDS)
    assert {"id": "sc1", "label": "Lightbulb", "group": "shortcut"} in result["keys"]
    assert result["context_values"][0] == "com.youtube"
    assert "com.netflix" in result["context_values"]


async def test_get_unknown_entry(hass, mqtt_mock, setup_entry, hass_ws_client):
    """Unknown entry ids are reported as not_found."""
    client = await hass_ws_client(hass)
    msg = await _send(client, {"type": "astrion_remote/config/get", "entry_id": "nope"})
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"


async def test_commands_require_admin(hass, mqtt_mock, setup_entry, hass_ws_client, hass_read_only_access_token):
    """Every command is admin-only."""
    client = await hass_ws_client(hass, hass_read_only_access_token)
    config = setup_entry.options[CONF_CONFIG]
    for payload in (
        {"type": "astrion_remote/config/get", "entry_id": setup_entry.entry_id},
        {"type": "astrion_remote/config/validate", "entry_id": setup_entry.entry_id, "config": config},
        {"type": "astrion_remote/config/set", "entry_id": setup_entry.entry_id, "config": config},
        {"type": "astrion_remote/tv_keys"},
    ):
        msg = await _send(client, payload)
        assert not msg["success"], payload["type"]
        assert msg["error"]["code"] == "unauthorized"


async def test_validate_ok_and_errors(hass, mqtt_mock, setup_entry, hass_ws_client):
    """config/validate reports per-path errors and never stores anything."""
    client = await hass_ws_client(hass)
    good = setup_entry.options[CONF_CONFIG]
    msg = await _send(
        client, {"type": "astrion_remote/config/validate", "entry_id": setup_entry.entry_id, "config": good}
    )
    assert msg["result"]["ok"] is True
    assert msg["result"]["errors"] == []

    bad = copy.deepcopy(good)
    bad["keys"]["sc1"] = {"tap": {"type": "ha", "action": "not an action"}}
    msg = await _send(
        client, {"type": "astrion_remote/config/validate", "entry_id": setup_entry.entry_id, "config": bad}
    )
    result = msg["result"]
    assert result["ok"] is False
    assert result["errors"][0]["path"][:3] == ["keys", "sc1", "tap"]
    assert "invalid action" in result["errors"][0]["msg"]

    dangling = copy.deepcopy(good)
    dangling["keys"]["sc2"] = {"tap": {"type": "page", "page": "missing"}}
    msg = await _send(
        client, {"type": "astrion_remote/config/validate", "entry_id": setup_entry.entry_id, "config": dangling}
    )
    assert msg["result"]["ok"] is False
    assert msg["result"]["errors"] == [
        {"path": ["keys", "sc2", "tap", "page"], "msg": "page action points to unknown page: missing"}
    ]
    assert setup_entry.options[CONF_CONFIG] == good


async def test_set_stores_and_publishes_retained(hass, mqtt_mock, setup_entry, hass_ws_client):
    """config/set validates, stores in the options and republishes the retained config."""
    client = await hass_ws_client(hass)
    config = copy.deepcopy(setup_entry.options[CONF_CONFIG])
    config["keys"]["sc1"] = {
        "tap": {"type": "ha", "action": "light.toggle", "target": {"entity_id": ["light.desk"]}},
        "hold": {"type": "tv_key", "key": "MY_CUSTOM_KEY", "hold": "repeat"},
        "contexts": {"com.netflix": {"double": {"type": "page", "page": "watch"}}},
    }
    config["allow"] = ["ignored"]
    mqtt_mock.async_publish.reset_mock()
    msg = await _send(
        client, {"type": "astrion_remote/config/set", "entry_id": setup_entry.entry_id, "config": config}
    )
    assert msg["success"], msg
    await hass.async_block_till_done()
    stored = setup_entry.options[CONF_CONFIG]
    assert "allow" not in stored
    assert stored["keys"]["sc1"]["contexts"]["com.netflix"]["double"] == {"type": "page", "page": "watch"}
    assert msg["result"]["config"] == json.loads(json.dumps(stored))
    calls = _published(mqtt_mock)
    assert len(calls) == 1
    _topic, payload, qos, retain = calls[0].args
    assert retain is True and qos == 1
    published = json.loads(payload)
    assert "light.toggle:light.desk" in published["allow"]
    assert published["keys"]["sc1"]["hold"]["key"] == "MY_CUSTOM_KEY"


async def test_set_unchanged_still_publishes(hass, mqtt_mock, setup_entry, hass_ws_client):
    """Saving the same config republishes it (explicit save)."""
    client = await hass_ws_client(hass)
    mqtt_mock.async_publish.reset_mock()
    msg = await _send(
        client,
        {
            "type": "astrion_remote/config/set",
            "entry_id": setup_entry.entry_id,
            "config": setup_entry.options[CONF_CONFIG],
        },
    )
    assert msg["success"]
    await hass.async_block_till_done()
    assert len(_published(mqtt_mock)) == 1


async def test_set_invalid_is_rejected(hass, mqtt_mock, setup_entry, hass_ws_client):
    """An invalid config is not stored and nothing is published."""
    client = await hass_ws_client(hass)
    before = copy.deepcopy(setup_entry.options[CONF_CONFIG])
    bad = copy.deepcopy(before)
    bad["pages"] = []
    mqtt_mock.async_publish.reset_mock()
    msg = await _send(client, {"type": "astrion_remote/config/set", "entry_id": setup_entry.entry_id, "config": bad})
    assert not msg["success"]
    assert msg["error"]["code"] == "invalid_format"
    assert "pages" in msg["error"]["message"]
    await hass.async_block_till_done()
    assert setup_entry.options[CONF_CONFIG] == before
    assert _published(mqtt_mock) == []


async def test_tv_keys(hass, mqtt_mock, setup_entry, hass_ws_client):
    """tv_keys lists the picker's key names."""
    client = await hass_ws_client(hass)
    msg = await _send(client, {"type": "astrion_remote/tv_keys"})
    assert msg["result"]["keys"] == list(TV_KEYS)
    assert "DPAD_CENTER" in TV_KEYS and "MEDIA_AUDIO_TRACK" in TV_KEYS


async def test_panel_registered_and_removed(hass, mqtt_mock, setup_entry, hass_client):
    """Admin-only sidebar panel with a module served from frontend/; removed with the last remote."""
    panel = hass.data[DATA_PANELS]["astrion-remote"]
    assert panel.sidebar_title == "Astrion Remote"
    assert panel.sidebar_icon == "mdi:remote-tv"
    assert panel.require_admin is True
    custom = panel.config["_panel_custom"]
    assert custom["name"] == "astrion-remote-panel"
    url = custom["module_url"]
    assert url.startswith("/astrion_remote_static/astrion-panel.js?v=")

    client = await hass_client()
    resp = await client.get(url.split("?")[0])
    assert resp.status == 200
    assert "customElements.define" in await resp.text()

    # Unloading keeps it (the editor works while MQTT is down); deleting the last remote drops it.
    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    await hass.async_block_till_done()
    assert "astrion-remote" in hass.data[DATA_PANELS]
    await hass.config_entries.async_remove(setup_entry.entry_id)
    await hass.async_block_till_done()
    assert "astrion-remote" not in hass.data[DATA_PANELS]


async def test_panel_and_ws_without_mqtt_connection(hass, mqtt_mock, config_entry, hass_ws_client):
    """Entry not ready (MQTT down): the panel is still there and config/set stores the options."""
    from unittest.mock import patch

    from homeassistant.config_entries import ConfigEntryState

    config_entry.add_to_hass(hass)
    with patch(
        "custom_components.astrion_remote.mqtt.async_wait_for_mqtt_client", return_value=False
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert "astrion-remote" in hass.data[DATA_PANELS]
    client = await hass_ws_client(hass)
    config = copy.deepcopy(config_entry.options[CONF_CONFIG])
    config["keys"]["mute"] = {"tap": {"type": "tv_key", "key": "MUTE"}}
    msg = await _send(client, {"type": "astrion_remote/config/set", "entry_id": config_entry.entry_id, "config": config})
    assert msg["success"], msg
    assert config_entry.options[CONF_CONFIG]["keys"]["mute"]["tap"]["key"] == "MUTE"
