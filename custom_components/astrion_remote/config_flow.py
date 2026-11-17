"""Config and options flow for Astrion Remote."""

from __future__ import annotations

import copy
import re
from typing import Any

import voluptuous as vol
import yaml

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector as sel

from .apk import validate_base_url, validate_subdir
from .const import (
    ACTION_TYPES,
    APP_CMDS,
    CONF_APK_DIR,
    CONF_BASE_URL,
    CONF_BASE_TOPIC,
    CONF_CONFIG,
    CONF_DEVICE_ID,
    DEFAULT_BASE_TOPIC,
    DEFAULT_BASE_URL,
    DEFAULT_DEVICE_ID,
    DOMAIN,
    GESTURES,
    KEY_IDS,
    THEME_MODES,
    TV_HOLD_MODES,
)
from .default_config import DEFAULT_CONFIG
from .schema import ACTION, validate_config, validate_pages

_DEVICE_ID_RE = re.compile(r"^[a-z0-9_-]+$")


def _valid_base_topic(topic: str) -> bool:
    return bool(topic) and not any(c in topic for c in "+#") and not topic.startswith("/") and "//" not in topic


def _select(options: list[str] | tuple[str, ...], key: str | None = None, mode=sel.SelectSelectorMode.DROPDOWN):
    config = sel.SelectSelectorConfig(options=list(options), mode=mode)
    if key:
        config["translation_key"] = key
    return sel.SelectSelector(config)


class AstrionConfigFlow(ConfigFlow, domain=DOMAIN):
    """One entry per remote."""

    VERSION = 1
    MINOR_VERSION = 4

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the device id and base topic."""
        if not mqtt.mqtt_config_entry_enabled(self.hass):
            return self.async_abort(reason="mqtt_not_configured")
        errors: dict[str, str] = {}
        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID].strip().lower()
            base = user_input[CONF_BASE_TOPIC].strip().rstrip("/")
            if not _DEVICE_ID_RE.match(device_id):
                errors[CONF_DEVICE_ID] = "invalid_device_id"
            elif not _valid_base_topic(base):
                errors[CONF_BASE_TOPIC] = "invalid_topic"
            else:
                await self.async_set_unique_id(device_id)
                self._abort_if_unique_id_configured()
                self._async_abort_entries_match({CONF_BASE_TOPIC: base})
                return self.async_create_entry(
                    title=f"Astrion Remote ({device_id})",
                    data={CONF_DEVICE_ID: device_id, CONF_BASE_TOPIC: base},
                    options={
                        CONF_CONFIG: validate_config(DEFAULT_CONFIG),
                        CONF_APK_DIR: "",
                        CONF_BASE_URL: DEFAULT_BASE_URL,
                    },
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID, default=DEFAULT_DEVICE_ID): str,
                vol.Required(CONF_BASE_TOPIC, default=DEFAULT_BASE_TOPIC): str,
            }
        )
        if user_input:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Options flow."""
        return AstrionOptionsFlow()


def _to_selector_action(action: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not action or action.get("type") != "ha":
        return []
    out: dict[str, Any] = {"action": action["action"]}
    if "target" in action:
        out["target"] = copy.deepcopy(action["target"])
    if action.get("data"):
        out["data"] = copy.deepcopy(action["data"])
    return [out]


def _from_selector_action(value: Any) -> dict[str, Any]:
    items = value if isinstance(value, list) else [value] if value else []
    if len(items) != 1 or not isinstance(items[0], dict):
        raise vol.Invalid("pick exactly one action")
    item = items[0]
    name = item.get("action") or item.get("service")
    if not name:
        raise vol.Invalid("only service/action calls are supported")
    action: dict[str, Any] = {"type": "ha", "action": name}
    if item.get("target"):
        action["target"] = item["target"]
    if item.get("data"):
        action["data"] = item["data"]
    return ACTION(action)


class AstrionOptionsFlow(OptionsFlow):
    """Menu-driven editor for the remote config."""

    def __init__(self) -> None:
        self._key: str = ""
        self._gesture: str = ""

    @property
    def _config(self) -> dict[str, Any]:
        return copy.deepcopy(self.config_entry.options.get(CONF_CONFIG) or DEFAULT_CONFIG)

    def _save(self, config: dict[str, Any], **extra: Any) -> ConfigFlowResult:
        options = {**self.config_entry.options, CONF_CONFIG: validate_config(config), **extra}
        return self.async_create_entry(data=options)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Menu."""
        return self.async_show_menu(step_id="init", menu_options=["keys", "pages", "timings", "yaml"])

    # ---- keys --------------------------------------------------------------------------------
    async def async_step_keys(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick key, gesture and action type."""
        if user_input is not None:
            self._key = user_input["key"]
            self._gesture = user_input["gesture"]
            action_type = user_input["action_type"]
            if action_type in ("event", "none"):
                return self._save_key_action({"type": action_type})
            return await getattr(self, f"async_step_key_{action_type}")()
        schema = vol.Schema(
            {
                vol.Required("key"): _select(KEY_IDS, "key"),
                vol.Required("gesture", default="tap"): _select(GESTURES, "gesture", sel.SelectSelectorMode.LIST),
                vol.Required("action_type"): _select(ACTION_TYPES, "action_type"),
            }
        )
        return self.async_show_form(step_id="keys", data_schema=schema)

    def _current_action(self) -> dict[str, Any] | None:
        return self._config.get("keys", {}).get(self._key, {}).get(self._gesture)

    def _save_key_action(self, action: dict[str, Any]) -> ConfigFlowResult:
        config = self._config
        config.setdefault("keys", {}).setdefault(self._key, {})[self._gesture] = action
        return self._save(config)

    def _placeholders(self) -> dict[str, str]:
        return {"key": self._key, "gesture": self._gesture}

    async def async_step_key_ha(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Home Assistant action (allowlisted automatically)."""
        errors: dict[str, str] = {}
        placeholders = {**self._placeholders(), "error": ""}
        if user_input is not None:
            try:
                action = _from_selector_action(user_input.get("action"))
            except vol.Invalid as err:
                errors["base"] = "invalid_action"
                placeholders["error"] = str(err)
            else:
                if self._gesture == "hold" and user_input.get("repeat"):
                    action["repeat"] = True
                return self._save_key_action(action)
        current = self._current_action()
        fields: dict[Any, Any] = {
            vol.Required("action", default=_to_selector_action(current)): sel.ActionSelector()
        }
        if self._gesture == "hold":
            fields[vol.Optional("repeat", default=bool(current and current.get("repeat")))] = (
                sel.BooleanSelector()
            )
        return self.async_show_form(
            step_id="key_ha", data_schema=vol.Schema(fields), errors=errors, description_placeholders=placeholders
        )

    async def async_step_key_tv_key(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """TV key sent straight to Control Freak."""
        if user_input is not None:
            return self._save_key_action(
                {"type": "tv_key", "key": user_input["tv_key"].strip().upper(), "hold": user_input["hold"]}
            )
        current = self._current_action() or {}
        is_tv = current.get("type") == "tv_key"
        schema = vol.Schema(
            {
                vol.Required("tv_key", default=current.get("key", "") if is_tv else ""): sel.TextSelector(),
                vol.Required("hold", default=current.get("hold", "passthrough") if is_tv else "passthrough"): _select(
                    TV_HOLD_MODES, "tv_hold"
                ),
            }
        )
        return self.async_show_form(
            step_id="key_tv_key", data_schema=schema, description_placeholders=self._placeholders()
        )

    async def async_step_key_page(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Switch page."""
        if user_input is not None:
            return self._save_key_action({"type": "page", "page": user_input["page"]})
        pages = ["next", "prev", *[p["id"] for p in self._config.get("pages", [])]]
        schema = vol.Schema({vol.Required("page"): _select(pages)})
        return self.async_show_form(
            step_id="key_page", data_schema=schema, description_placeholders=self._placeholders()
        )

    async def async_step_key_app(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Local app command."""
        if user_input is not None:
            return self._save_key_action({"type": "app", "cmd": user_input["cmd"]})
        schema = vol.Schema({vol.Required("cmd"): _select(APP_CMDS, "app_cmd")})
        return self.async_show_form(
            step_id="key_app", data_schema=schema, description_placeholders=self._placeholders()
        )

    # ---- pages -------------------------------------------------------------------------------
    async def async_step_pages(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Edit pages as YAML (object selector)."""
        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        config = self._config
        if user_input is not None:
            try:
                config["pages"] = validate_pages(user_input["pages"])
                return self._save(config)
            except vol.Invalid as err:
                errors["base"] = "invalid_pages"
                placeholders["error"] = str(err)
        default = user_input["pages"] if user_input else config["pages"]
        schema = vol.Schema({vol.Required("pages", default=default): sel.ObjectSelector()})
        return self.async_show_form(
            step_id="pages", data_schema=schema, errors=errors, description_placeholders=placeholders
        )

    # ---- timings & theme ---------------------------------------------------------------------
    async def async_step_timings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Timings, theme, TV, APK directory and the HA URL for APK downloads."""
        errors: dict[str, str] = {}
        config = self._config
        if user_input is not None:
            config["timings"] = {k: int(user_input[k]) for k in ("hold_ms", "double_ms", "keepalive_ms")}
            config["theme"] = {"mode": user_input["theme_mode"], "calm": user_input["calm"]}
            config["tv"] = {"keytopic": user_input["keytopic"].strip()}
            if user_input.get("context_entity"):
                config["tv"]["context_entity"] = user_input["context_entity"]
            try:
                apk_dir = validate_subdir(user_input.get(CONF_APK_DIR, ""))
            except ValueError:
                errors[CONF_APK_DIR] = "invalid_apk_dir"
            try:
                base_url = validate_base_url(user_input.get(CONF_BASE_URL, ""))
            except ValueError:
                errors[CONF_BASE_URL] = "invalid_base_url"
            if not errors:
                try:
                    return self._save(config, **{CONF_APK_DIR: apk_dir, CONF_BASE_URL: base_url})
                except vol.Invalid:
                    errors["base"] = "invalid_timings"
        timings = config.get("timings", {})
        theme = config.get("theme", {})
        tv = config.get("tv", {})

        def num(lo: int, hi: int, step: int) -> sel.NumberSelector:
            return sel.NumberSelector(
                sel.NumberSelectorConfig(
                    min=lo, max=hi, step=step, unit_of_measurement="ms", mode=sel.NumberSelectorMode.BOX
                )
            )

        fields: dict[Any, Any] = {
            vol.Required("hold_ms", default=timings.get("hold_ms", 450)): num(100, 3000, 10),
            vol.Required("double_ms", default=timings.get("double_ms", 350)): num(100, 2000, 10),
            vol.Required("keepalive_ms", default=timings.get("keepalive_ms", 300)): num(50, 3000, 10),
            vol.Required("theme_mode", default=theme.get("mode", "auto")): _select(
                THEME_MODES, "theme_mode", sel.SelectSelectorMode.LIST
            ),
            vol.Required("calm", default=theme.get("calm", False)): sel.BooleanSelector(),
            vol.Required(
                "keytopic", default=tv.get("keytopic", "controlfreak/hisense_tv/key/set")
            ): sel.TextSelector(),
        }
        if tv.get("context_entity"):
            fields[vol.Optional("context_entity", default=tv["context_entity"])] = sel.EntitySelector()
        else:
            fields[vol.Optional("context_entity")] = sel.EntitySelector()
        fields[vol.Optional(CONF_APK_DIR, default=self.config_entry.options.get(CONF_APK_DIR, ""))] = (
            sel.TextSelector()
        )
        base_url = (
            user_input.get(CONF_BASE_URL, "")
            if user_input is not None
            else self.config_entry.options.get(CONF_BASE_URL, DEFAULT_BASE_URL)
        )
        fields[vol.Optional(CONF_BASE_URL, description={"suggested_value": base_url})] = sel.TextSelector(
            sel.TextSelectorConfig(type=sel.TextSelectorType.URL)
        )
        return self.async_show_form(step_id="timings", data_schema=vol.Schema(fields), errors=errors)

    # ---- import / export ---------------------------------------------------------------------
    async def async_step_yaml(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Full config as YAML: copy it out, or paste a new one in."""
        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        if user_input is not None:
            try:
                parsed = yaml.safe_load(user_input["config"])
                return self._save(validate_config(parsed))
            except yaml.YAMLError as err:
                errors["base"] = "invalid_yaml"
                placeholders["error"] = str(err)
            except vol.Invalid as err:
                errors["base"] = "invalid_config"
                placeholders["error"] = str(err)
            text = user_input["config"]
        else:
            text = yaml.safe_dump(self._config, sort_keys=False, allow_unicode=True, width=120)
        schema = vol.Schema(
            {vol.Required("config", default=text): sel.TextSelector(sel.TextSelectorConfig(multiline=True))}
        )
        return self.async_show_form(
            step_id="yaml", data_schema=schema, errors=errors, description_placeholders=placeholders
        )
