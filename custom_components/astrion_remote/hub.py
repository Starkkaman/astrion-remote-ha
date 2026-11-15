"""MQTT hub for one Astrion remote: config publish, state mirror, call/event/telemetry handling."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Protocol

import voluptuous as vol

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.json import json_dumps
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.storage import Store

from .const import (
    CONF_APK_DIR,
    CONF_BASE_URL,
    CONF_BASE_TOPIC,
    CONF_CONFIG,
    CONF_DEVICE_ID,
    DOMAIN,
    EVENT_BUTTON,
    EVENT_GESTURES,
    MIRRORED_ATTRIBUTES,
    SIGNAL_UPDATE,
    STATE_MIN_INTERVAL,
    TOPIC_CALL,
    TOPIC_CMD,
    TOPIC_CONFIG,
    TOPIC_EVENT,
    TOPIC_STATE,
    TOPIC_STATUS,
    TOPIC_TELEMETRY,
    TOPIC_VOICE_AUDIO,
    TOPIC_VOICE_END,
    TOPIC_VOICE_EVENT,
    TOPIC_VOICE_START,
    TOPIC_VOICE_STOP,
    VOICE_RATE,
)
from .default_config import DEFAULT_CONFIG
from .schema import (
    build_published_config,
    entity_ids,
    is_call_allowed,
    referenced_entities,
    validate_config,
)

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1

_monotonic = time.monotonic  # patchable in tests

# Telemetry field aliases -> canonical key.
_TELEMETRY_ALIASES = {
    "battery": "battery",
    "battery_level": "battery",
    "charging": "charging",
    "screen": "screen",
    "screen_on": "screen",
    "page": "page",
    "app_version": "app_version",
    "version": "app_version",
    "wifi_rssi": "wifi_rssi",
    "rssi": "wifi_rssi",
    "last_key": "last_key",
    "ts": "ts",
}


_RUN_ID_MAX = 64


class VoiceSink(Protocol):
    """What the hub hands voice messages to (the assist_satellite entity)."""

    def voice_start(self, run: str, rate: int) -> None:
        """A new run started; cancels any previous one."""

    def voice_audio(self, run: str, chunk: bytes) -> None:
        """One PCM16 chunk of a run."""

    def voice_end(self, run: str) -> None:
        """The app stopped sending audio for a run."""


def _run_id(value: Any) -> str | None:
    if isinstance(value, str) and 0 < len(value) <= _RUN_ID_MAX and "/" not in value:
        return value
    return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("on", "true", "1", "yes", "charging"):
            return True
        if v in ("off", "false", "0", "no", "discharging"):
            return False
    return None


class AstrionHub:
    """Everything one remote needs on the HA side."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.remote_id: str = entry.data[CONF_DEVICE_ID]
        self.base: str = entry.data[CONF_BASE_TOPIC].rstrip("/")
        self.config: dict[str, Any] = {}
        self.allow: set[str] = set()
        self.mirrored: set[str] = set()
        self.telemetry: dict[str, Any] = {}
        self.online: bool | None = None
        self.device_id: str | None = None  # device registry id
        self._unsubs: list[CALLBACK_TYPE] = []
        self._unsub_track: CALLBACK_TYPE | None = None
        self._last_sent: dict[str, float] = {}
        self._last_payload: dict[str, str] = {}
        self._pending: dict[str, CALLBACK_TYPE] = {}
        self.satellite: VoiceSink | None = None  # set by the assist_satellite entity
        self._store: Store[dict[str, Any]] = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")

    # ---- helpers -------------------------------------------------------------------------
    def topic(self, sub: str) -> str:
        """Full topic for a sub-topic."""
        return f"{self.base}/{sub}"

    @property
    def signal(self) -> str:
        """Dispatcher signal for entity updates."""
        return SIGNAL_UPDATE.format(self.entry.entry_id)

    @property
    def apk_subdir(self) -> str:
        """Configured APK sub directory (relative to /config/astrion_remote)."""
        return self.entry.options.get(CONF_APK_DIR, "") or ""

    @property
    def base_url(self) -> str:
        """HA URL reachable from the remote ("" = use HA's own internal URL)."""
        return (self.entry.options.get(CONF_BASE_URL, "") or "").strip().rstrip("/")

    @property
    def device_info(self) -> DeviceInfo:
        """Device info shared by all entities."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.remote_id)},
            name="Astrion Remote",
            manufacturer="Astrion",
            model="HA100",
            sw_version=self.telemetry.get("app_version"),
        )

    @property
    def home_page(self) -> str:
        """First page id."""
        pages = self.config.get("pages") or [{"id": "now"}]
        return pages[0]["id"]

    # ---- lifecycle -----------------------------------------------------------------------
    async def async_start(self) -> None:
        """Subscribe, publish config and start mirroring."""
        device = dr.async_get(self.hass).async_get_or_create(
            config_entry_id=self.entry.entry_id, **self.device_info
        )
        self.device_id = device.id

        stored = await self._store.async_load() or {}
        self.mirrored = set(stored.get("mirrored", []))

        self._unsubs.append(await mqtt.async_subscribe(self.hass, self.topic(TOPIC_CALL), self._on_call))
        self._unsubs.append(await mqtt.async_subscribe(self.hass, self.topic(TOPIC_EVENT), self._on_event))
        self._unsubs.append(
            await mqtt.async_subscribe(self.hass, self.topic(TOPIC_TELEMETRY), self._on_telemetry)
        )
        self._unsubs.append(await mqtt.async_subscribe(self.hass, self.topic(TOPIC_STATUS), self._on_status))
        self._unsubs.append(
            await mqtt.async_subscribe(self.hass, self.topic(TOPIC_VOICE_START), self._on_voice_start)
        )
        self._unsubs.append(
            await mqtt.async_subscribe(
                self.hass, self.topic(f"{TOPIC_VOICE_AUDIO}/+"), self._on_voice_audio, encoding=None
            )
        )
        self._unsubs.append(await mqtt.async_subscribe(self.hass, self.topic(TOPIC_VOICE_END), self._on_voice_end))

        await self.async_apply_options()

    async def async_stop(self) -> None:
        """Unsubscribe everything (retained topics stay so the remote keeps working)."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._unsub_track:
            self._unsub_track()
            self._unsub_track = None
        for cancel in self._pending.values():
            cancel()
        self._pending.clear()

    async def async_clear_retained(self) -> None:
        """Clear the config and all mirrored state topics (entry removal)."""
        stored = await self._store.async_load() or {}
        for eid in set(stored.get("mirrored", [])) | self.mirrored:
            await mqtt.async_publish(self.hass, self.topic(f"{TOPIC_STATE}/{eid}"), "", retain=True)
        await mqtt.async_publish(self.hass, self.topic(TOPIC_CONFIG), "", retain=True)
        await self._store.async_remove()

    async def async_apply_options(self) -> None:
        """(Re)load the config from the entry options, publish it and resync the mirror."""
        raw = self.entry.options.get(CONF_CONFIG) or DEFAULT_CONFIG
        try:
            self.config = validate_config(raw)
        except Exception as err:  # noqa: BLE001 - stored config should always be valid
            _LOGGER.error("Stored Astrion config is invalid (%s); using the default", err)
            self.config = validate_config(DEFAULT_CONFIG)
        await self.async_publish_config()
        await self._async_sync_mirror()
        async_dispatcher_send(self.hass, self.signal)

    async def async_publish_config(self) -> None:
        """Publish <base>/config (retained)."""
        published = build_published_config(self.config)
        self.allow = set(published["allow"])
        await mqtt.async_publish(
            self.hass,
            self.topic(TOPIC_CONFIG),
            json.dumps(published, separators=(",", ":"), ensure_ascii=False),
            qos=1,
            retain=True,
        )

    async def async_send_cmd(self, cmd: str) -> None:
        """Publish a command to <base>/cmd (not retained)."""
        await mqtt.async_publish(self.hass, self.topic(TOPIC_CMD), cmd, qos=1, retain=False)

    @callback
    def voice_publish(self, sub: str, data: dict[str, Any]) -> None:
        """Publish a voice message (voice/event or voice/stop); never retained."""
        self.hass.async_create_task(
            mqtt.async_publish(
                self.hass,
                self.topic(sub),
                json.dumps(data, separators=(",", ":"), ensure_ascii=False),
                qos=1,
                retain=False,
            ),
            eager_start=True,
        )

    @callback
    def voice_event(self, run: str, stage: str, **fields: Any) -> None:
        """Publish <base>/voice/event for a run (None fields are left out)."""
        data: dict[str, Any] = {"run": run, "stage": stage}
        data.update({k: v for k, v in fields.items() if v is not None})
        self.voice_publish(TOPIC_VOICE_EVENT, data)

    @callback
    def voice_stop(self, run: str) -> None:
        """Ask the app to stop recording a run (<base>/voice/stop)."""
        self.voice_publish(TOPIC_VOICE_STOP, {"run": run})

    # ---- state mirror --------------------------------------------------------------------
    async def _async_sync_mirror(self) -> None:
        wanted = referenced_entities(self.config)
        for eid in sorted(self.mirrored - wanted):
            self._cancel_pending(eid)
            self._last_payload.pop(eid, None)
            self._last_sent.pop(eid, None)
            await mqtt.async_publish(self.hass, self.topic(f"{TOPIC_STATE}/{eid}"), "", qos=1, retain=True)
        added = wanted - self.mirrored
        self.mirrored = wanted
        await self._store.async_save({"mirrored": sorted(wanted)})

        if self._unsub_track:
            self._unsub_track()
        self._unsub_track = async_track_state_change_event(self.hass, sorted(wanted), self._on_state_change)

        # Publish everything once (dedup suppresses unchanged payloads on re-apply).
        for eid in sorted(wanted):
            if eid in added or eid not in self._last_payload:
                self._schedule_state(eid)

    @callback
    def _on_state_change(self, event: Event[EventStateChangedData]) -> None:
        self._schedule_state(event.data["entity_id"])

    def _cancel_pending(self, eid: str) -> None:
        if cancel := self._pending.pop(eid, None):
            cancel()

    @callback
    def _schedule_state(self, eid: str) -> None:
        """Publish now, or coalesce into one trailing publish to stay <= 4 msg/s."""
        if eid in self._pending:
            return  # trailing publish already scheduled; it will read the latest state
        wait = self._last_sent.get(eid, 0.0) + STATE_MIN_INTERVAL - _monotonic()
        if wait <= 0:
            self._publish_state(eid)
            return

        @callback
        def _fire(_now: Any) -> None:
            self._pending.pop(eid, None)
            self._publish_state(eid)

        self._pending[eid] = async_call_later(self.hass, wait, _fire)

    def state_payload(self, state: State | None) -> str:
        """Compact {"s":..,"a":{..}} for a state."""
        if state is None:
            return json_dumps({"s": STATE_UNAVAILABLE, "a": {}})
        attrs = {k: state.attributes[k] for k in MIRRORED_ATTRIBUTES if k in state.attributes}
        pic = attrs.get("entity_picture")
        if isinstance(pic, str) and pic.startswith("/"):
            try:
                attrs["entity_picture"] = get_url(self.hass, prefer_external=False, allow_cloud=False) + pic
            except NoURLAvailableError:
                pass
        return json_dumps({"s": state.state, "a": attrs})

    @callback
    def _publish_state(self, eid: str) -> None:
        if eid not in self.mirrored:
            return
        payload = self.state_payload(self.hass.states.get(eid))
        if self._last_payload.get(eid) == payload:
            return
        self._last_payload[eid] = payload
        self._last_sent[eid] = _monotonic()
        self.hass.async_create_task(
            mqtt.async_publish(self.hass, self.topic(f"{TOPIC_STATE}/{eid}"), payload, qos=0, retain=True),
            eager_start=True,
        )

    # ---- inbound -------------------------------------------------------------------------
    @staticmethod
    def _json(msg: mqtt.ReceiveMessage) -> dict[str, Any] | None:
        try:
            data = json.loads(msg.payload)
        except (ValueError, TypeError):
            return None
        return data if isinstance(data, dict) else None

    async def _on_call(self, msg: mqtt.ReceiveMessage) -> None:
        data = self._json(msg)
        if data is None:
            _LOGGER.warning("Astrion %s: ignoring malformed call payload", self.remote_id)
            return
        action = data.get("action")
        target = data.get("target") or {}
        service_data = dict(data.get("data") or {})
        try:
            if not isinstance(action, str) or action.count(".") != 1:
                raise ValueError("bad action")
            if not isinstance(target, dict) or not isinstance(service_data, dict):
                raise ValueError("bad target/data")
            extra = (set(target) - {"entity_id"}) | (
                set(service_data) & {"area_id", "device_id", "floor_id", "label_id"}
            )
            if extra:
                raise ValueError(f"non-entity targets not allowed: {sorted(extra)}")
            ids: list[str] = []
            for source in (target.get("entity_id"), service_data.pop("entity_id", None)):
                if source:
                    ids.extend(entity_ids(source))
            ids = list(dict.fromkeys(ids))
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Astrion %s: refused call %s: %s", self.remote_id, data.get("id"), err)
            return

        if not is_call_allowed(self.allow, action, ids):
            _LOGGER.warning(
                "Astrion %s: refused call %s: %s on %s is not in the allowlist",
                self.remote_id,
                data.get("id"),
                action,
                ids or "(no target)",
            )
            return

        domain, service = action.split(".", 1)
        try:
            await self.hass.services.async_call(
                domain,
                service,
                service_data,
                blocking=True,
                target={"entity_id": ids} if ids else None,
            )
        except (HomeAssistantError, ValueError, vol.Invalid) as err:
            _LOGGER.warning("Astrion %s: call %s %s failed: %s", self.remote_id, data.get("id"), action, err)

    @callback
    def _on_event(self, msg: mqtt.ReceiveMessage) -> None:
        data = self._json(msg)
        if data is None or not isinstance(data.get("key"), str) or data.get("gesture") not in EVENT_GESTURES:
            _LOGGER.debug("Astrion %s: ignoring malformed event %s", self.remote_id, msg.payload)
            return
        self.hass.bus.async_fire(
            EVENT_BUTTON,
            {
                "device_id": self.device_id,
                "remote_id": self.remote_id,
                "key": data["key"],
                "gesture": data["gesture"],
                "ctx": data.get("ctx"),
            },
        )

    @callback
    def _on_telemetry(self, msg: mqtt.ReceiveMessage) -> None:
        data = self._json(msg)
        if data is None:
            return
        for key, value in data.items():
            canon = _TELEMETRY_ALIASES.get(key)
            if canon is None:
                continue
            if canon in ("charging", "screen"):
                value = _as_bool(value)
            elif canon in ("battery", "wifi_rssi"):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = None
            elif value is not None:
                value = str(value)
            self.telemetry[canon] = value
        if version := self.telemetry.get("app_version"):
            dev_reg = dr.async_get(self.hass)
            if self.device_id and (device := dev_reg.async_get(self.device_id)) and device.sw_version != version:
                dev_reg.async_update_device(self.device_id, sw_version=version)
        async_dispatcher_send(self.hass, self.signal)

    @callback
    def _on_status(self, msg: mqtt.ReceiveMessage) -> None:
        payload = str(msg.payload).strip().lower()
        if payload == "online":
            self.online = True
        elif payload == "offline":
            self.online = False
        else:
            return
        async_dispatcher_send(self.hass, self.signal)

    # ---- voice ---------------------------------------------------------------------------
    @callback
    def _on_voice_start(self, msg: mqtt.ReceiveMessage) -> None:
        data = self._json(msg)
        run = _run_id(data.get("run")) if data else None
        if data is None or run is None:
            _LOGGER.debug("Astrion %s: ignoring malformed voice/start %s", self.remote_id, msg.payload)
            return
        rate = data.get("rate", VOICE_RATE)
        if rate != VOICE_RATE:
            self.voice_event(run, "error", error=f"unsupported sample rate {rate}")
            return
        if self.satellite is None:
            self.voice_event(run, "error", error="Assist satellite is not available")
            return
        self.satellite.voice_start(run, rate)

    @callback
    def _on_voice_audio(self, msg: mqtt.ReceiveMessage) -> None:
        run = _run_id(msg.topic.rsplit("/", 1)[-1])
        payload = msg.payload
        if run is None or self.satellite is None or not isinstance(payload, (bytes, bytearray)) or not payload:
            return
        self.satellite.voice_audio(run, bytes(payload))

    @callback
    def _on_voice_end(self, msg: mqtt.ReceiveMessage) -> None:
        data = self._json(msg)
        run = _run_id(data.get("run")) if data else None
        if run is None or self.satellite is None:
            return
        self.satellite.voice_end(run)
