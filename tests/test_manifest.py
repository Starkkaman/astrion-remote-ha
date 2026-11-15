"""hassfest-style sanity checks for manifest, strings, translations and services."""

import json
from pathlib import Path

from awesomeversion import AwesomeVersion
import yaml

from homeassistant.loader import async_get_integration

from custom_components.astrion_remote.const import ACTION_TYPES, DOMAIN, GESTURES, KEY_IDS

ROOT = Path(__file__).parents[1] / "custom_components" / DOMAIN


def _json(name):
    return json.loads((ROOT / name).read_text())


def test_manifest_valid():
    """Required keys for a custom integration."""
    manifest = _json("manifest.json")
    for key in ("domain", "name", "codeowners", "documentation", "issue_tracker", "requirements", "version"):
        assert key in manifest, key
    assert manifest["domain"] == DOMAIN
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "local_push"
    assert "mqtt" in manifest["dependencies"]
    assert AwesomeVersion(manifest["version"]).valid
    hacs = json.loads((ROOT.parents[1] / "hacs.json").read_text())
    assert hacs["name"]


async def test_manifest_loads(hass):
    """HA's loader accepts the manifest."""
    integration = await async_get_integration(hass, DOMAIN)
    assert integration.config_flow
    assert integration.dependencies == ["frontend", "http", "mqtt", "panel_custom"]


def test_translations_match_strings():
    """translations/en.json mirrors strings.json and covers every step, selector and trigger."""
    strings = _json("strings.json")
    assert strings == _json("translations/en.json")
    steps = strings["options"]["step"]
    for step in ("init", "keys", "key_ha", "key_tv_key", "key_page", "key_app", "pages", "timings", "yaml"):
        assert step in steps, step
    assert set(steps["init"]["menu_options"]) == {"keys", "pages", "timings", "yaml"}
    assert "user" in strings["config"]["step"]
    assert set(strings["selector"]["key"]["options"]) == set(KEY_IDS)
    assert set(strings["selector"]["action_type"]["options"]) == set(ACTION_TYPES)
    assert set(strings["device_automation"]["trigger_type"]) == set(GESTURES)
    assert set(strings["device_automation"]["trigger_subtype"]) == set(KEY_IDS)
    for platform, keys in {
        "sensor": {"battery", "page", "app_version", "wifi_rssi", "last_key"},
        "binary_sensor": {"charging", "screen", "connectivity"},
        "button": {"reload_config", "home_page"},
        "update": {"app"},
    }.items():
        assert set(strings["entity"][platform]) == keys


def test_services_have_strings():
    """Every service in services.yaml has a name and field strings."""
    services = yaml.safe_load((ROOT / "services.yaml").read_text())
    strings = _json("strings.json")["services"]
    icons = _json("icons.json")["services"]
    assert set(services) == set(strings) == set(icons)
    for name, spec in services.items():
        assert strings[name]["name"]
        assert set(spec.get("fields", {})) == set(strings[name].get("fields", {}))
