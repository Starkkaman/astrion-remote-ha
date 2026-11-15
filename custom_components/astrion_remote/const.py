"""Constants for the Astrion Remote integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "astrion_remote"

CONF_DEVICE_ID: Final = "device_id"
CONF_BASE_TOPIC: Final = "base_topic"
CONF_CONFIG: Final = "config"
CONF_APK_DIR: Final = "apk_dir"
CONF_BASE_URL: Final = "base_url"

DEFAULT_DEVICE_ID: Final = "ha100"
DEFAULT_BASE_TOPIC: Final = "astrion/ha100"
# HA URL the remote uses to download APKs (empty = HA's own internal URL).
DEFAULT_BASE_URL: Final = "http://192.168.5.166:8123"

# Directory (under the HA config dir) that holds astrion-<version>.apk files.
APK_ROOT_DIRNAME: Final = "astrion_remote"

SCHEMA_VERSION: Final = 1

# Topics relative to the base topic (see docs/ARCHITECTURE.md).
TOPIC_STATUS: Final = "status"
TOPIC_CONFIG: Final = "config"
TOPIC_STATE: Final = "state"
TOPIC_EVENT: Final = "event"
TOPIC_CALL: Final = "call"
TOPIC_CMD: Final = "cmd"
TOPIC_TELEMETRY: Final = "telemetry"
# Voice (HA Assist over MQTT, see "Voice" in docs/ARCHITECTURE.md).
TOPIC_VOICE_START: Final = "voice/start"
TOPIC_VOICE_AUDIO: Final = "voice/audio"  # + "/<run>", binary PCM16 mono 16 kHz
TOPIC_VOICE_END: Final = "voice/end"
TOPIC_VOICE_STOP: Final = "voice/stop"
TOPIC_VOICE_EVENT: Final = "voice/event"
VOICE_RATE: Final = 16000
VOICE_TARGETS: Final = ("ha", "tv")
# The app caps a run at 8 s; the audio stream ends by itself after this many seconds.
VOICE_AUDIO_TIMEOUT: Final = 10.0

EVENT_BUTTON: Final = "astrion_remote_button"

KEY_IDS: Final = (
    "back",
    "home",
    "power",
    "voice",
    "sc1",
    "sc2",
    "sc3",
    "sc4",
    "red",
    "green",
    "yellow",
    "blue",
    "up",
    "down",
    "left",
    "right",
    "ok",
    "menu",
    "page_up",
    "page_down",
    "vol_up",
    "vol_down",
    "mute",
)
GESTURES: Final = ("tap", "double", "hold")
# Human labels and physical groups (top to bottom on the remote) for the panel.
KEY_LABELS: Final = {
    "back": "Back",
    "home": "Home",
    "power": "Power",
    "voice": "Voice",
    "sc1": "Lightbulb",
    "sc2": "Curtains",
    "sc3": "Music",
    "sc4": "Climate",
    "red": "Red",
    "green": "Green",
    "yellow": "Yellow",
    "blue": "Blue",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "ok": "OK",
    "menu": "Menu",
    "page_up": "Page +",
    "page_down": "Page -",
    "vol_up": "Vol +",
    "vol_down": "Vol -",
    "mute": "Mute",
}
KEY_GROUPS: Final = {
    "back": "top",
    "home": "top",
    "power": "top",
    "voice": "voice",
    "up": "dpad",
    "down": "dpad",
    "left": "dpad",
    "right": "dpad",
    "ok": "dpad",
    "menu": "menu",
    "page_up": "page",
    "page_down": "page",
    "vol_up": "volume",
    "vol_down": "volume",
    "mute": "volume",
    "red": "color",
    "green": "color",
    "blue": "color",
    "yellow": "color",
    "sc1": "shortcut",
    "sc2": "shortcut",
    "sc3": "shortcut",
    "sc4": "shortcut",
}

# TV key names offered by the panel's key picker (free text is accepted too).
TV_KEYS: Final = (
    "DPAD_UP",
    "DPAD_DOWN",
    "DPAD_LEFT",
    "DPAD_RIGHT",
    "DPAD_CENTER",
    "BACK",
    "HOME",
    "MENU",
    "SEARCH",
    "MEDIA_PLAY_PAUSE",
    "MEDIA_REWIND",
    "MEDIA_FAST_FORWARD",
    "MEDIA_NEXT",
    "MEDIA_PREVIOUS",
    "CHANNEL_UP",
    "CHANNEL_DOWN",
    "CAPTIONS",
    "MEDIA_AUDIO_TRACK",
    "VOLUME_UP",
    "VOLUME_DOWN",
    "MUTE",
    "SETTINGS",
    "INFO",
)

# Sidebar panel.
PANEL_URL_PATH: Final = "astrion-remote"
PANEL_TITLE: Final = "Astrion Remote"
PANEL_ICON: Final = "mdi:remote-tv"
PANEL_COMPONENT: Final = "astrion-remote-panel"
PANEL_STATIC_URL: Final = "/astrion_remote_static"
PANEL_JS: Final = "astrion-panel.js"
EVENT_GESTURES: Final = ("tap", "double", "hold", "hold_end")

ACTION_TYPES: Final = ("tv_key", "ha", "event", "page", "app", "none")
SECTION_TYPES: Final = (
    "now_playing",
    "tiles",
    "segmented",
    "slider",
    "rocker",
    "switch",
    "keys",
)
TV_HOLD_MODES: Final = ("passthrough", "repeat", "none")
APP_CMDS: Final = ("settings", "reload")
THEME_MODES: Final = ("auto", "day", "night")

# Attributes mirrored to <base>/state/<entity_id> (subset; only present ones are sent).
MIRRORED_ATTRIBUTES: Final = (
    "friendly_name",
    "icon",
    "unit_of_measurement",
    "brightness",
    "color_mode",
    "supported_color_modes",
    "supported_features",
    "media_title",
    "media_series_title",
    "media_artist",
    "media_album_name",
    "media_content_type",
    "media_position",
    "media_position_updated_at",
    "media_duration",
    "app_name",
    "volume_level",
    "is_volume_muted",
    "entity_picture",
    "options",
    "source",
    "min",
    "max",
    "step",
    "mode",
)

# Max 4 messages per second per entity.
STATE_MIN_INTERVAL: Final = 0.25

APK_TOKEN_TTL: Final = 600  # seconds
APK_VIEW_URL: Final = "/api/astrion_remote/apk/{token}"

SIGNAL_UPDATE: Final = "astrion_remote_update_{}"

SERVICE_TOAST: Final = "toast"
SERVICE_PAGE: Final = "page"
SERVICE_RELOAD: Final = "reload"
