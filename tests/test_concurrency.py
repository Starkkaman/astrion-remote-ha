"""Config versions (stale_config), the config-changed event and lint warnings."""

import copy

from homeassistant.setup import async_setup_component

from custom_components.astrion_remote.config_events import config_version
from custom_components.astrion_remote.const import CONF_CONFIG, EVENT_CONFIG_CHANGED

from .conftest import BASE


async def _send(client, payload):
    await client.send_json_auto_id(payload)
    return await client.receive_json()


def _events(hass):
    seen = []
    hass.bus.async_listen(EVENT_CONFIG_CHANGED, lambda e: seen.append(dict(e.data)))
    return seen


def test_version_is_stable_and_short():
    """Same content in any key order -> same 16-hex version; any change -> a new one."""
    a = {"keys": {"ok": {"tap": {"type": "tv_key", "key": "OK"}}}, "pages": [], "timings": {"x": 1}}
    b = {"timings": {"x": 1}, "pages": [], "keys": {"ok": {"tap": {"key": "OK", "type": "tv_key"}}}}
    assert config_version(a) == config_version(b) == config_version(copy.deepcopy(a))
    assert len(config_version(a)) == 16
    int(config_version(a), 16)
    c = copy.deepcopy(a)
    c["timings"]["x"] = 2
    assert config_version(c) != config_version(a)


async def test_get_set_versions_and_stale(hass, mqtt_mock, setup_entry, hass_ws_client):
    """get/set return the version; a set with an old version is rejected and stores nothing."""
    client = await hass_ws_client(hass)
    eid = setup_entry.entry_id
    got = (await _send(client, {"type": "astrion_remote/config/get", "entry_id": eid}))["result"]
    v1 = got["version"]
    assert v1 == config_version(setup_entry.options[CONF_CONFIG])

    mine = copy.deepcopy(got["config"])
    mine["keys"]["sc1"] = {"tap": {"type": "tv_key", "key": "HOME"}}
    msg = await _send(client, {"type": "astrion_remote/config/set", "entry_id": eid, "config": mine, "version": v1})
    assert msg["success"], msg
    v2 = msg["result"]["version"]
    assert v2 != v1
    assert v2 == config_version(setup_entry.options[CONF_CONFIG])

    # A second editor still holding v1 must not overwrite.
    theirs = copy.deepcopy(got["config"])
    theirs["keys"]["sc2"] = {"tap": {"type": "tv_key", "key": "BACK"}}
    published = len(mqtt_mock.async_publish.call_args_list)
    msg = await _send(client, {"type": "astrion_remote/config/set", "entry_id": eid, "config": theirs, "version": v1})
    assert not msg["success"]
    assert msg["error"]["code"] == "stale_config"
    assert msg["error"]["message"] == "Someone else saved the remote config; reload and try again"
    await hass.async_block_till_done()
    assert config_version(setup_entry.options[CONF_CONFIG]) == v2
    assert setup_entry.options[CONF_CONFIG]["keys"]["sc1"]["tap"]["key"] == "HOME"
    assert not [c for c in mqtt_mock.async_publish.call_args_list[published:] if c.args[0] == f"{BASE}/config"]

    got = (await _send(client, {"type": "astrion_remote/config/get", "entry_id": eid}))["result"]
    assert got["version"] == v2


async def test_set_without_version_still_saves(hass, mqtt_mock, setup_entry, hass_ws_client):
    """Clients that do not send a version keep last-write-wins."""
    client = await hass_ws_client(hass)
    config = copy.deepcopy(setup_entry.options[CONF_CONFIG])
    config["keys"]["sc3"] = {"tap": {"type": "tv_key", "key": "MUTE"}}
    msg = await _send(
        client, {"type": "astrion_remote/config/set", "entry_id": setup_entry.entry_id, "config": config}
    )
    assert msg["success"], msg
    assert msg["result"]["version"] == config_version(setup_entry.options[CONF_CONFIG])
    assert setup_entry.options[CONF_CONFIG]["keys"]["sc3"]["tap"]["key"] == "MUTE"


async def test_event_fired_on_set_reset_undo(hass, mqtt_mock, setup_entry, hass_ws_client):
    """astrion_remote_config_changed {entry_id, version} after every store that changes the config."""
    seen = _events(hass)
    client = await hass_ws_client(hass)
    eid = setup_entry.entry_id
    config = copy.deepcopy(setup_entry.options[CONF_CONFIG])
    config["keys"]["sc1"] = {"tap": {"type": "tv_key", "key": "HOME"}}
    msg = await _send(client, {"type": "astrion_remote/config/set", "entry_id": eid, "config": config})
    await hass.async_block_till_done()
    assert seen == [{"entry_id": eid, "version": msg["result"]["version"]}]

    msg = await _send(client, {"type": "astrion_remote/config/reset", "entry_id": eid, "parts": ["keys"]})
    assert msg["success"], msg
    await hass.async_block_till_done()
    assert seen[-1] == {"entry_id": eid, "version": msg["result"]["version"]}
    assert len(seen) == 2

    msg = await _send(client, {"type": "astrion_remote/config/undo_reset", "entry_id": eid})
    assert msg["success"], msg
    await hass.async_block_till_done()
    assert seen[-1] == {"entry_id": eid, "version": msg["result"]["version"]}
    assert len(seen) == 3


async def test_event_fired_on_options_flow(hass, mqtt_mock, setup_entry):
    """The options flow stores through the entry too, so it fires the event."""
    seen = _events(hass)
    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "keys"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"key": "sc1", "gesture": "tap", "action_type": "tv_key"}
    )
    await hass.config_entries.options.async_configure(result["flow_id"], {"tv_key": "home", "hold": "none"})
    await hass.async_block_till_done()
    assert seen == [
        {"entry_id": setup_entry.entry_id, "version": config_version(setup_entry.options[CONF_CONFIG])}
    ]


async def _warnings(hass, client, entry, config):
    msg = await _send(client, {"type": "astrion_remote/config/validate", "entry_id": entry.entry_id, "config": config})
    assert msg["success"], msg
    assert msg["result"]["ok"] is True
    return msg["result"]["warnings"]


async def test_warning_untargeted_service(hass, mqtt_mock, setup_entry, hass_ws_client):
    """scene.turn_on (from HA's service description) and light.toggle (fallback) need a target."""
    assert await async_setup_component(hass, "scene", {})
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)
    config = copy.deepcopy(setup_entry.options[CONF_CONFIG])
    config["keys"]["sc1"] = {"tap": {"type": "ha", "action": "scene.turn_on"}}
    config["keys"]["sc2"] = {"tap": {"type": "ha", "action": "light.toggle"}}
    config["keys"]["sc3"] = {"tap": {"type": "ha", "action": "scene.turn_on", "target": {"entity_id": "scene.movie"}}}
    config["keys"]["sc4"] = {"tap": {"type": "ha", "action": "light.toggle", "data": {"entity_id": "light.desk"}}}
    config["keys"]["red"] = {"tap": {"type": "ha", "action": "scene.reload"}}
    warnings = await _warnings(hass, client, setup_entry, config)
    by_key = {tuple(w["path"][:2]): w for w in warnings if w["path"][0] == "keys"}
    assert by_key[("keys", "sc1")]["path"] == ["keys", "sc1", "tap"]
    assert "scene.turn_on needs a target" in by_key[("keys", "sc1")]["msg"]
    assert ("keys", "sc2") in by_key
    assert ("keys", "sc3") not in by_key
    assert ("keys", "sc4") not in by_key
    assert ("keys", "red") not in by_key


async def test_warning_missing_entity(hass, mqtt_mock, setup_entry, hass_ws_client):
    """Sections and choose actions pointing at entities that do not exist are flagged (get too)."""
    client = await hass_ws_client(hass)
    config = copy.deepcopy(setup_entry.options[CONF_CONFIG])
    config["pages"][0]["sections"] = [
        {"type": "switch", "entity": "switch.gone"},
        {"type": "rocker", "entity": "light.here"},
    ]
    config["keys"]["sc1"] = {"tap": {"type": "choose", "entity": "select.gone"}}
    hass.states.async_set("light.here", "on")
    warnings = await _warnings(hass, client, setup_entry, config)
    paths = [w["path"] for w in warnings]
    assert ["pages", 0, "sections", 0, "entity"] in paths
    assert ["pages", 0, "sections", 1, "entity"] not in paths
    assert ["keys", "sc1", "tap", "entity"] in paths
    assert any("switch.gone does not exist" in w["msg"] for w in warnings)

    hass.config_entries.async_update_entry(setup_entry, options={**setup_entry.options, CONF_CONFIG: config})
    await hass.async_block_till_done()
    got = await _send(client, {"type": "astrion_remote/config/get", "entry_id": setup_entry.entry_id})
    assert ["pages", 0, "sections", 0, "entity"] in [w["path"] for w in got["result"]["warnings"]]
