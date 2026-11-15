"""Options flow tests (menu: keys, pages, timings, yaml) and config republish."""

import json

import yaml

from homeassistant.data_entry_flow import FlowResultType

from custom_components.astrion_remote.const import CONF_APK_DIR, CONF_BASE_URL, CONF_CONFIG

from .conftest import BASE


async def _open(hass, entry, step):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["keys", "pages", "timings", "yaml"]
    return await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": step})


def _last_config(mqtt_mock):
    calls = [c for c in mqtt_mock.async_publish.call_args_list if c.args[0] == f"{BASE}/config"]
    topic, payload, qos, retain = calls[-1].args
    assert retain is True
    return json.loads(payload)


async def test_key_ha_action_and_republish(hass, mqtt_mock, setup_entry):
    """Map sc1 tap to a light action; config is republished retained with the new allow entry."""
    result = await _open(hass, setup_entry, "keys")
    assert result["step_id"] == "keys"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"key": "sc1", "gesture": "tap", "action_type": "ha"}
    )
    assert result["step_id"] == "key_ha"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "action": [
                {
                    "action": "light.turn_on",
                    "metadata": {},
                    "target": {"entity_id": "light.desk"},
                    "data": {"brightness_pct": 40},
                }
            ]
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    sc1 = setup_entry.options[CONF_CONFIG]["keys"]["sc1"]["tap"]
    assert sc1 == {
        "type": "ha",
        "action": "light.turn_on",
        "target": {"entity_id": ["light.desk"]},
        "data": {"brightness_pct": 40},
    }
    published = _last_config(mqtt_mock)
    assert published["keys"]["sc1"]["tap"]["action"] == "light.turn_on"
    assert "light.turn_on:light.desk" in published["allow"]
    assert setup_entry.runtime_data.allow >= {"light.turn_on:light.desk"}


async def test_key_ha_rejects_area_target(hass, mqtt_mock, setup_entry):
    """Only entity targets are allowed (the allowlist is per entity)."""
    result = await _open(hass, setup_entry, "keys")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"key": "sc2", "gesture": "hold", "action_type": "ha"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"action": [{"action": "light.turn_on", "target": {"area_id": "kitchen"}}], "repeat": True}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_action"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"action": [{"action": "script.turn_on", "target": {"entity_id": ["script.x"]}}], "repeat": True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_entry.options[CONF_CONFIG]["keys"]["sc2"]["hold"]["repeat"] is True


async def test_key_tv_page_app_event(hass, mqtt_mock, setup_entry):
    """The other action types."""
    result = await _open(hass, setup_entry, "keys")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"key": "sc3", "gesture": "double", "action_type": "tv_key"}
    )
    assert result["step_id"] == "key_tv_key"
    await hass.config_entries.options.async_configure(result["flow_id"], {"tv_key": "home", "hold": "none"})
    assert setup_entry.options[CONF_CONFIG]["keys"]["sc3"]["double"] == {"type": "tv_key", "key": "HOME", "hold": "none"}

    result = await _open(hass, setup_entry, "keys")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"key": "sc4", "gesture": "tap", "action_type": "page"}
    )
    assert result["step_id"] == "key_page"
    await hass.config_entries.options.async_configure(result["flow_id"], {"page": "music"})
    assert setup_entry.options[CONF_CONFIG]["keys"]["sc4"]["tap"] == {"type": "page", "page": "music"}

    result = await _open(hass, setup_entry, "keys")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"key": "menu", "gesture": "hold", "action_type": "app"}
    )
    await hass.config_entries.options.async_configure(result["flow_id"], {"cmd": "settings"})
    assert setup_entry.options[CONF_CONFIG]["keys"]["menu"]["hold"] == {"type": "app", "cmd": "settings"}

    result = await _open(hass, setup_entry, "keys")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"key": "red", "gesture": "hold", "action_type": "event"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_entry.options[CONF_CONFIG]["keys"]["red"]["hold"] == {"type": "event"}
    await hass.async_block_till_done()


async def test_pages_edit(hass, mqtt_mock, setup_entry):
    """Pages are validated against the schema."""
    result = await _open(hass, setup_entry, "pages")
    assert result["step_id"] == "pages"
    bad = [{"id": "x", "title": "X", "sections": [{"type": "rocker"}]}]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"pages": bad})
    assert result["errors"] == {"base": "invalid_pages"}
    # Default page actions (home -> now) must still resolve, so keep `now`.
    good = [
        {"id": "now", "title": "Now", "sections": [{"type": "rocker", "entity": "light.desk"}]},
        {"id": "music", "title": "Music", "sections": []},
    ]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"pages": good})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    published = _last_config(mqtt_mock)
    assert [p["id"] for p in published["pages"]] == ["now", "music"]
    assert "light.toggle:light.desk" in published["allow"]


async def test_pages_unknown_page_ref(hass, mqtt_mock, setup_entry):
    """Removing a page that a key points to is refused."""
    result = await _open(hass, setup_entry, "pages")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"pages": [{"id": "music", "title": "Music"}]}
    )
    # validate_pages passes, the full config check (home -> now) fails
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_pages"}


async def test_timings(hass, mqtt_mock, setup_entry):
    """Timings, theme, tv, apk dir."""
    result = await _open(hass, setup_entry, "timings")
    assert result["step_id"] == "timings"
    user = {
        "hold_ms": 500,
        "double_ms": 300,
        "keepalive_ms": 250,
        "theme_mode": "night",
        "calm": True,
        "keytopic": "controlfreak/hisense_tv/key/set",
        "context_entity": "sensor.hisense_tv_current_app",
        CONF_APK_DIR: "../etc",
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], user)
    assert result["errors"] == {CONF_APK_DIR: "invalid_apk_dir"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {**user, CONF_APK_DIR: "apks"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    config = setup_entry.options[CONF_CONFIG]
    assert config["timings"] == {"hold_ms": 500, "double_ms": 300, "keepalive_ms": 250}
    assert config["theme"] == {"mode": "night", "calm": True}
    assert setup_entry.options[CONF_APK_DIR] == "apks"
    assert _last_config(mqtt_mock)["timings"]["hold_ms"] == 500


async def test_timings_base_url(hass, mqtt_mock, setup_entry):
    """base_url is edited in Timings & theme; must be http(s)://host[:port] without a path."""
    result = await _open(hass, setup_entry, "timings")
    schema_keys = {str(k): k for k in result["data_schema"].schema}
    assert schema_keys[CONF_BASE_URL].description == {"suggested_value": "http://192.168.5.166:8123"}
    user = {
        "hold_ms": 450,
        "double_ms": 350,
        "keepalive_ms": 300,
        "theme_mode": "auto",
        "calm": False,
        "keytopic": "controlfreak/hisense_tv/key/set",
    }
    for bad in ("192.168.5.20:8123", "http://192.168.5.20:8123/lovelace", "ftp://192.168.5.20"):
        result = await hass.config_entries.options.async_configure(result["flow_id"], {**user, CONF_BASE_URL: bad})
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {CONF_BASE_URL: "invalid_base_url"}
    assert setup_entry.options[CONF_BASE_URL] == "http://192.168.5.166:8123"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**user, CONF_BASE_URL: "https://192.168.5.20:8123/"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert setup_entry.options[CONF_BASE_URL] == "https://192.168.5.20:8123"
    assert setup_entry.options[CONF_APK_DIR] == ""

    # cleared field (frontend omits it) -> empty -> fall back to HA's internal URL
    result = await _open(hass, setup_entry, "timings")
    result = await hass.config_entries.options.async_configure(result["flow_id"], user)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert setup_entry.options[CONF_BASE_URL] == ""
    assert setup_entry.runtime_data.base_url == ""


async def test_yaml_import_export(hass, mqtt_mock, setup_entry):
    """Export shows the current config; import validates and replaces it."""
    result = await _open(hass, setup_entry, "yaml")
    schema_default = next(iter(result["data_schema"].schema)).default()
    exported = yaml.safe_load(schema_default)
    assert exported["pages"][0]["id"] == "now"

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"config": "pages: [unclosed"})
    assert result["errors"] == {"base": "invalid_yaml"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"config": "pages:\n  - id: a\n    title: A\n    sections:\n      - type: bogus\n"}
    )
    assert result["errors"] == {"base": "invalid_config"}

    exported["theme"]["calm"] = True
    exported["allow"] = ["evil.service:lock.front_door"]  # ignored, always recomputed
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"config": yaml.safe_dump(exported)}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert setup_entry.options[CONF_CONFIG]["theme"]["calm"] is True
    published = _last_config(mqtt_mock)
    assert "evil.service:lock.front_door" not in published["allow"]
