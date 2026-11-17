"""v3 design: the choose action, visible_if, tile size, new defaults and the 1.3 -> 1.4 migration."""

from __future__ import annotations

import copy
import json
import logging
import shutil
import subprocess
from pathlib import Path

import pytest
import voluptuous as vol
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.astrion_remote import migrate_v3_defaults
from custom_components.astrion_remote.const import (
    CONF_BASE_TOPIC,
    CONF_BASE_URL,
    CONF_CONFIG,
    CONF_DEVICE_ID,
    DEFAULT_BASE_URL,
    DOMAIN,
)
from custom_components.astrion_remote.default_config import (
    DEFAULT_CONFIG,
    OLD_COLOUR_KEY_TAPS,
    OLD_DEFAULT_PAGES_0_3_0,
)
from custom_components.astrion_remote.schema import (
    ACTION,
    DECORATED_ACTION,
    SECTION,
    compute_allowlist,
    referenced_entities,
    validate_config,
)

ROOT = Path(__file__).parents[1] / "custom_components" / DOMAIN
IDLE = ["off", "idle", "unavailable", "standby"]
COLOURS = ("red", "green", "yellow", "blue")


# ---- schema ----------------------------------------------------------------------------------
@pytest.mark.parametrize("entity", ["select.phoster_subtitles", "input_select.light_scenes"])
def test_choose_action_accepted(entity):
    assert ACTION({"type": "choose", "entity": entity}) == {"type": "choose", "entity": entity}
    action = {"type": "choose", "entity": entity, "title": "Pick", "label": "L", "icon": "mdi:x"}
    assert DECORATED_ACTION(action) == action


@pytest.mark.parametrize(
    "action",
    [
        {"type": "choose"},
        {"type": "choose", "entity": "light.lamp"},
        {"type": "choose", "entity": ""},
        {"type": "choose", "entity": "select.x", "option": "a"},
        {"type": "choose", "entity": "select.x", "title": 3},
    ],
)
def test_choose_action_rejected(action):
    with pytest.raises(vol.Invalid):
        ACTION(action)


@pytest.mark.parametrize("mode", ["state_not", "state_in"])
def test_visible_if_accepted_on_every_section(mode):
    cond = {"entity": "media_player.tv", mode: ["off", "idle"]}
    sections = [
        {"type": "now_playing", "entity": "media_player.tv"},
        {"type": "tiles", "items": [{"label": "A", "size": "quick"}]},
        {"type": "segmented", "entity": "select.x"},
        {"type": "slider", "entity": "number.x"},
        {"type": "rocker", "entity": "light.x"},
        {"type": "switch", "entity": "switch.x"},
        {"type": "keys", "items": [{"label": "A", "action": {"type": "none"}}]},
    ]
    for section in sections:
        assert SECTION({**section, "visible_if": cond})["visible_if"] == cond


@pytest.mark.parametrize(
    "cond",
    [
        {"entity": "media_player.tv"},
        {"entity": "media_player.tv", "state_not": ["off"], "state_in": ["on"]},
        {"state_not": ["off"]},
        {"entity": "media_player.tv", "state_not": "off"},
        {"entity": "media_player.tv", "state_not": [1]},
        {"entity": "media_player.tv", "state_is": ["off"]},
    ],
)
def test_visible_if_rejected(cond):
    with pytest.raises(vol.Invalid):
        SECTION({"type": "switch", "entity": "switch.x", "visible_if": cond})


def _cfg(pages=None, keys=None):
    return validate_config(
        {
            "keys": keys or {},
            "pages": pages or [{"id": "p", "title": "P", "sections": []}],
        }
    )


def test_choose_allowlist_and_mirror():
    config = _cfg(
        keys={"red": {"tap": {"type": "choose", "entity": "select.subs"}}},
        pages=[
            {
                "id": "p",
                "title": "P",
                "sections": [
                    {
                        "type": "now_playing",
                        "entity": "media_player.tv",
                        "buttons": [{"type": "choose", "entity": "input_select.scenes", "label": "S"}],
                    }
                ],
            }
        ],
    )
    allow = compute_allowlist(config)
    assert "select.select_option:select.subs" in allow
    assert "input_select.select_option:input_select.scenes" in allow
    assert not [a for a in allow if "select_next" in a and "subs" in a]
    assert {"select.subs", "input_select.scenes"} <= referenced_entities(config)


def test_visible_if_entity_mirrored():
    config = _cfg(
        pages=[
            {
                "id": "p",
                "title": "P",
                "sections": [
                    {"type": "switch", "entity": "switch.x", "visible_if": {"entity": "sensor.cond", "state_in": ["on"]}}
                ],
            }
        ]
    )
    assert "sensor.cond" in referenced_entities(config)
    # Mirroring a condition entity does not allow calls on it.
    assert not [a for a in compute_allowlist(config) if a.endswith(":sensor.cond")]


def test_rocker_allows_turn_on_with_data():
    from custom_components.astrion_remote.schema import is_call_allowed

    config = _cfg(pages=[{"id": "p", "title": "P", "sections": [{"type": "rocker", "entity": "light.lamp"}]}])
    # The allowlist is action:entity only; data such as brightness_pct is not restricted.
    assert is_call_allowed(set(compute_allowlist(config)), "light.turn_on", ["light.lamp"])


def test_options_attribute_mirrored():
    from custom_components.astrion_remote.const import MIRRORED_ATTRIBUTES

    assert "options" in MIRRORED_ATTRIBUTES


# ---- defaults --------------------------------------------------------------------------------
def test_default_config_v3():
    config = validate_config(DEFAULT_CONFIG)
    assert "select_next" not in json.dumps(config)
    assert config["theme"]["mode"] == "night"
    assert {c: config["keys"][c]["tap"] for c in COLOURS} == {
        "red": {"type": "choose", "entity": "select.phoster_subtitles", "title": "Subtitles"},
        "green": {"type": "choose", "entity": "select.phoster_audio_track", "title": "Audio"},
        "yellow": {"type": "choose", "entity": "input_select.light_scenes", "title": "Scene"},
        "blue": {"type": "choose", "entity": "select.hisense_tv_picture_mode", "title": "Picture"},
    }
    pages = {p["id"]: p for p in config["pages"]}
    assert list(pages) == ["now", "watch", "room", "music"]
    now = pages["now"]["sections"]
    assert [s["type"] for s in now] == ["now_playing", "segmented", "segmented", "tiles"]
    assert now[0]["visible_if"] == {"entity": "media_player.phoster_3", "state_not": IDLE}
    assert [b["type"] for b in now[0]["buttons"]][:2] == ["choose", "choose"]
    assert now[0]["buttons"][-1]["action"] == "media_player.media_play_pause"
    quick = now[3]
    assert quick["title"] == "Quick" and quick["columns"] == 2
    assert quick["visible_if"] == {"entity": "media_player.phoster_3", "state_in": IDLE}
    assert [i["label"] for i in quick["items"]] == ["Jamfin TV", "YouTube", "Netflix", "Switch"]
    watch_tv = next(s for s in pages["watch"]["sections"] if s["type"] == "keys")
    assert [i["label"] for i in watch_tv["items"]] == ["Power", "Home"]
    players = next(s for s in pages["music"]["sections"] if s["type"] == "tiles")
    assert players["columns"] == 2 and len(players["items"]) == 4
    allow = compute_allowlist(config)
    assert "media_player.media_play_pause:media_player.phoster_3" in allow
    assert "select.select_option:select.phoster_subtitles" in allow


# ---- migration -------------------------------------------------------------------------------
def _old_config(**changes) -> dict:
    """A stored 0.3.0 config (as the config flow saved it)."""
    config = validate_config(DEFAULT_CONFIG)
    config["theme"] = {"mode": "auto", "calm": False}
    for colour, tap in OLD_COLOUR_KEY_TAPS.items():
        config["keys"][colour] = {"tap": copy.deepcopy(tap)}
    config["pages"] = validate_config({"pages": OLD_DEFAULT_PAGES_0_3_0})["pages"]
    config.update(changes)
    return config


def test_migrate_untouched_default():
    old = _old_config()
    out = migrate_v3_defaults(old)
    assert out is not None
    assert out["pages"] == DEFAULT_CONFIG["pages"]
    for colour in COLOURS:
        assert out["keys"][colour]["tap"] == DEFAULT_CONFIG["keys"][colour]["tap"]
    assert out["theme"] == {"mode": "auto", "calm": False}  # theme is the user's
    assert old["pages"] == validate_config({"pages": OLD_DEFAULT_PAGES_0_3_0})["pages"]  # input untouched
    validate_config(out)


def test_migrate_raw_unnormalised_default_pages():
    """Pages equal to the default but stored without schema defaults (columns, buttons) still match."""
    out = migrate_v3_defaults(_old_config(pages=copy.deepcopy(OLD_DEFAULT_PAGES_0_3_0)))
    assert out["pages"] == DEFAULT_CONFIG["pages"]


def test_migrate_preserves_user_edits(caplog):
    old = _old_config()
    old["keys"]["red"] = {"tap": {"type": "tv_key", "key": "RED"}}
    old["keys"]["green"]["tap"]["data"] = {"cycle": False}  # not exactly the old default
    old["keys"]["yellow"]["hold"] = {"type": "event"}  # tap still default: tap migrates, hold kept
    old["pages"][0]["title"] = "Mine"
    with caplog.at_level(logging.INFO):
        out = migrate_v3_defaults(old)
    assert out["keys"]["red"] == {"tap": {"type": "tv_key", "key": "RED"}}
    assert out["keys"]["green"] == old["keys"]["green"]
    assert out["keys"]["yellow"] == {"tap": DEFAULT_CONFIG["keys"]["yellow"]["tap"], "hold": {"type": "event"}}
    assert out["keys"]["blue"]["tap"] == DEFAULT_CONFIG["keys"]["blue"]["tap"]
    assert out["pages"] == old["pages"]
    assert len([r for r in caplog.records if "keeping your pages" in r.message]) == 1


def test_migrate_nothing_to_do():
    config = validate_config(DEFAULT_CONFIG)
    config["pages"][0]["title"] = "Mine"
    assert migrate_v3_defaults(config) is None


@pytest.mark.parametrize("edited", [False, True])
async def test_entry_migration_1_3_to_1_4(hass, mqtt_mock, edited):
    old = _old_config()
    if edited:
        old["pages"].append({"id": "extra", "title": "Extra", "sections": []})
        old["keys"]["blue"] = {"tap": {"type": "none"}}
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="ha100",
        data={CONF_DEVICE_ID: "ha100", CONF_BASE_TOPIC: "astrion/ha100"},
        options={CONF_CONFIG: old, CONF_BASE_URL: DEFAULT_BASE_URL},
        minor_version=3,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 4
    stored = entry.options[CONF_CONFIG]
    assert stored["theme"]["mode"] == "auto"
    assert stored["keys"]["red"]["tap"]["type"] == "choose"
    if edited:
        assert stored["pages"] == old["pages"]
        assert stored["keys"]["blue"] == {"tap": {"type": "none"}}
    else:
        assert stored["pages"] == DEFAULT_CONFIG["pages"]
        assert stored["keys"]["blue"]["tap"]["type"] == "choose"


# ---- panel -----------------------------------------------------------------------------------
def test_panel_js_v3():
    node = shutil.which("node") or "/home/isaac/.local/opt/node-v22.23.5-linux-x64/bin/node"
    if not Path(node).exists():
        pytest.skip("node not available")
    js = ROOT / "frontend" / "astrion-panel.js"
    result = subprocess.run([node, "--check", str(js)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    text = js.read_text()
    assert '["choose", "Choose from list"]' in text
    assert 'case "choose":' in text
    assert "Show only when" in text and "state_not" in text and "state_in" in text
