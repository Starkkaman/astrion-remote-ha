"""Constants for the Astrion Remote integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "astrion_remote"

CONF_DEVICE_ID: Final = "device_id"
CONF_BASE_TOPIC: Final = "base_topic"
CONF_CONFIG: Final = "config"
CONF_APK_DIR: Final = "apk_dir"
CONF_BASE_URL: Final = "base_url"
# App updates: where APKs come from (GitHub releases or the APK folder), which repo, and auto-install.
CONF_UPDATE_SOURCE: Final = "update_source"
CONF_GITHUB_REPO: Final = "github_repo"
CONF_AUTO_INSTALL: Final = "auto_install"
# Options: the config as it was before the last reset_to_defaults (one-step undo).
CONF_PREVIOUS_CONFIG: Final = "previous_config"

DEFAULT_DEVICE_ID: Final = "ha100"
DEFAULT_BASE_TOPIC: Final = "astrion/ha100"
# HA URL the remote uses to download APKs (empty = HA's own internal URL).
DEFAULT_BASE_URL: Final = "http://192.168.5.166:8123"

UPDATE_SOURCE_GITHUB: Final = "github"
UPDATE_SOURCE_FOLDER: Final = "folder"
UPDATE_SOURCES: Final = (UPDATE_SOURCE_GITHUB, UPDATE_SOURCE_FOLDER)
DEFAULT_UPDATE_SOURCE: Final = UPDATE_SOURCE_GITHUB
DEFAULT_GITHUB_REPO: Final = "Starkkaman/astrion-remote-ha"
DEFAULT_AUTO_INSTALL: Final = False

# Directory (under the HA config dir) that holds astrion-<version>.apk files (folder source), and where
# APKs downloaded from GitHub are kept.
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
# Fired with {entry_id, version} whenever a remote's stored config changes (see config_events.py).
EVENT_CONFIG_CHANGED: Final = "astrion_remote_config_changed"
# Fired with {device_id, remote_id, state} when the remote is picked up / put down (app motion sensing).
EVENT_MOTION: Final = "astrion_remote_motion"
MOTION_STATES: Final = ("picked_up", "put_down")
# tv.transport: how tv_key actions reach the TV. Apps that do not know a value fall back to auto.
TV_TRANSPORTS: Final = ("auto", "atv", "controlfreak", "bluetooth", "ir")
# tv.wake_via: how Auto wakes a sleeping TV. Absent = bluetooth (the app default).
TV_WAKE_VIA: Final = ("bluetooth", "ir", "none")
# Telemetry `kiosk` values.
KIOSK_STATES: Final = ("on", "off", "paused")

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

# Hisense (Phoster) IR codes, NEC extended, address 0xBF00, 38 kHz (astrion-remote docs/ir.md).
# Name -> command. Vendor shortcut keys and 0x1A (sleep) are left out on purpose.
HISENSE_IR_ADDRESS: Final = 0xBF00
HISENSE_IR: Final = (
    ("Power", 0x0D),
    ("Power (alt)", 0xD1),
    ("Up", 0x16),
    ("Down", 0x17),
    ("Left", 0x19),
    ("Right", 0x18),
    ("OK", 0x15),
    ("Back", 0x48),
    ("Home", 0x94),
    ("Menu", 0x14),
    ("Settings", 0x0F),
    ("Volume up", 0x44),
    ("Volume down", 0x43),
    ("Mute", 0x0E),
    ("Play/Pause", 0x4E),
    ("Channel up", 0x4A),
    ("Channel down", 0x4B),
    ("Input", 0x12),
    *((str(n), n) for n in range(10)),
    ("Info", 0x0C),
    ("Rewind", 0x57),
    ("Fast forward", 0x56),
    ("Stop", 0x5A),
    ("Record", 0x74),
    ("Guide", 0x1D),
    ("Subtitles", 0x1F),
    ("Audio track", 0x1C),
    ("All apps", 0x5F),
    ("Live TV", 0x1B),
    ("Exit", 0x32),
    ("Search", 0xD5),
    ("Red", 0x52),
    ("Green", 0x53),
    ("Yellow", 0x54),
    ("Blue", 0x55),
    ("Teletext", 0x45),
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
IR_HOLD_MODES: Final = ("repeat", "none")
IR_PROTOCOLS: Final = ("nec",)
# ConsumerIrManager: discrete HA100 carriers lie in 30-56 kHz; a pattern over 2 s is refused.
IR_CARRIER_MIN: Final = 30000
IR_CARRIER_MAX: Final = 60000
IR_PATTERN_MAX_US: Final = 2_000_000
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
MAX_APK_BYTES: Final = 100 * 1024 * 1024  # same cap as the app's updater

GITHUB_API: Final = "https://api.github.com"
GITHUB_PER_PAGE: Final = 20
GITHUB_POLL_HOURS: Final = 6

SIGNAL_UPDATE: Final = "astrion_remote_update_{}"

SERVICE_TOAST: Final = "toast"
SERVICE_PAGE: Final = "page"
SERVICE_RELOAD: Final = "reload"
SERVICE_RESET_TO_DEFAULTS: Final = "reset_to_defaults"
SERVICE_UNDO_RESET: Final = "undo_reset"

# Top-level config parts reset_to_defaults can replace.
RESET_PARTS: Final = ("pages", "keys", "timings", "theme")
