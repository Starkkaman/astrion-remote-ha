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
