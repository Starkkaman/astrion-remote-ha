"""Default remote config used on first setup (Isaac's living room)."""

from __future__ import annotations

from typing import Any


def _ha(action: str, entity: str, data: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "ha", "action": action, "target": {"entity_id": [entity]}}
    if data:
        out["data"] = data
    out.update(extra)
    return out


def _tv(key: str, hold: str = "passthrough") -> dict[str, Any]:
    return {"type": "tv_key", "key": key, "hold": hold}


def _voice(target: str) -> dict[str, Any]:
    return {"type": "voice", "target": target}


def _cycle(entity: str) -> dict[str, Any]:
    domain = entity.split(".", 1)[0]
    return _ha(f"{domain}.select_next", entity, {"cycle": True})


def _script(entity: str, **extra: Any) -> dict[str, Any]:
    return _ha("script.turn_on", entity, **extra)


def _launch(app: str) -> dict[str, Any]:
    return {
        "label": app,
        "entity": "select.hisense_tv_launch_app",
        "action": _ha("select.select_option", "select.hisense_tv_launch_app", {"option": app}),
    }


_NONE = {"type": "none"}

# Voice key mappings shipped before 0.3.0 (tv SEARCH on tap). Entries whose voice key is still
# exactly this are moved to the new default on migration; anything else is the user's choice.
OLD_VOICE_DEFAULTS: tuple[dict[str, Any], ...] = (
    {"tap": _tv("SEARCH", "none")},
    {"tap": {"type": "tv_key", "key": "SEARCH"}},
)

DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 1,
    "timings": {"hold_ms": 450, "double_ms": 350, "keepalive_ms": 300},
    "tv": {
        "keytopic": "controlfreak/hisense_tv/key/set",
        "context_entity": "sensor.hisense_tv_current_app",
    },
    "theme": {"mode": "night", "calm": False},
    "keys": {
        "up": {"tap": _tv("DPAD_UP")},
        "down": {"tap": _tv("DPAD_DOWN")},
        "left": {"tap": _tv("DPAD_LEFT")},
        "right": {"tap": _tv("DPAD_RIGHT")},
        "ok": {"tap": _tv("DPAD_CENTER")},
        "back": {"tap": _tv("BACK")},
        "menu": {"tap": _tv("MENU")},
        "vol_up": {
            "tap": _script("script.stereo_volume_up"),
            "hold": _script("script.stereo_volume_up", repeat=True),
        },
        "vol_down": {
            "tap": _script("script.stereo_volume_down"),
            "hold": _script("script.stereo_volume_down", repeat=True),
        },
        "mute": {"tap": _ha("button.press", "button.stereo_volume_mute")},
        "page_up": {"tap": {"type": "page", "page": "prev"}},
        "page_down": {"tap": {"type": "page", "page": "next"}},
        "red": {"tap": _cycle("select.phoster_subtitles")},
        "green": {"tap": _cycle("select.phoster_audio_track")},
        "yellow": {"tap": _cycle("input_select.light_scenes")},
        "blue": {"tap": _cycle("select.hisense_tv_picture_mode")},
        "home": {"tap": {"type": "page", "page": "now"}, "double": _tv("HOME", "none")},
        "power": {"tap": {"type": "event"}},
        "voice": {"tap": _voice("ha"), "hold": _voice("tv")},
        "sc1": {"tap": dict(_NONE)},
        "sc2": {"tap": dict(_NONE)},
        "sc3": {"tap": dict(_NONE)},
        "sc4": {"tap": dict(_NONE)},
    },
    "pages": [
        {
            "id": "now",
            "title": "Now",
            "sections": [
                {
                    "type": "now_playing",
                    "entity": "media_player.phoster_3",
                    "buttons": [
                        {**_cycle("select.phoster_subtitles"), "label": "Subtitles", "icon": "mdi:subtitles"},
                        {**_cycle("select.phoster_audio_track"), "label": "Audio", "icon": "mdi:translate"},
                        {
                            **_ha("button.press", "button.phoster_previous_chapter"),
                            "label": "Prev chapter",
                            "icon": "mdi:skip-previous",
                        },
                        {
                            **_ha("button.press", "button.phoster_next_chapter"),
                            "label": "Next chapter",
                            "icon": "mdi:skip-next",
                        },
                        {
                            **_ha("button.press", "button.phoster_skip_segment"),
                            "label": "Skip",
                            "icon": "mdi:debug-step-over",
                        },
                    ],
                },
                {"type": "segmented", "entity": "select.hisense_tv_picture_mode", "title": "Picture"},
                {"type": "segmented", "entity": "select.hisense_tv_audio_output", "title": "Sound out"},
            ],
        },
        {
            "id": "watch",
            "title": "Watch",
            "sections": [
                {
                    "type": "tiles",
                    "title": "Apps",
                    "columns": 3,
                    "items": [
                        _launch(app)
                        for app in ("Jamfin TV", "YouTube", "Netflix", "Dropout", "Corridor TV")
                    ],
                },
                {
                    "type": "tiles",
                    "title": "Inputs",
                    "columns": 3,
                    "items": [
                        {
                            "label": "Nintendo",
                            "icon": "mdi:nintendo-switch",
                            "action": _script("script.nintendo_input"),
                        },
                        {
                            "label": "Batocera",
                            "icon": "mdi:gamepad-variant",
                            "action": _script("script.batocera_input_2"),
                        },
                        {
                            "label": "HDMI 2",
                            "icon": "mdi:video-input-hdmi",
                            "entity": "select.hisense_tv_input",
                            "action": _ha("select.select_option", "select.hisense_tv_input", {"option": "HDMI 2"}),
                        },
                    ],
                },
                {
                    "type": "keys",
                    "items": [
                        {"label": "TV power", "icon": "mdi:power", "action": _ha("switch.toggle", "switch.hisense_tv_power")}
                    ],
                },
                {
                    "type": "slider",
                    "title": "Backlight",
                    "entity": "number.hisense_tv_backlight",
                    "action": _ha("number.set_value", "number.hisense_tv_backlight"),
                },
            ],
        },
        {
            "id": "room",
            "title": "Room",
            "sections": [
                {"type": "segmented", "entity": "input_select.light_scenes", "title": "Scene"},
                {"type": "rocker", "entity": "light.living_room_floor_lamp"},
                {"type": "rocker", "entity": "light.kajplats_e26_cws_globe_1100lm"},
                {"type": "rocker", "entity": "light.living_room"},
                {"type": "switch", "entity": "light.wled"},
                {
                    "type": "keys",
                    "title": "Stereo",
                    "items": [
                        {"label": "Vol -", "icon": "mdi:volume-minus", "action": _script("script.stereo_volume_down")},
                        {"label": "Mute", "icon": "mdi:volume-mute", "action": _ha("button.press", "button.stereo_volume_mute")},
                        {"label": "Vol +", "icon": "mdi:volume-plus", "action": _script("script.stereo_volume_up")},
                        {"label": "Power", "icon": "mdi:power", "action": _script("script.stereo_power")},
                    ],
                },
                {
                    "type": "keys",
                    "title": "Stereo input",
                    "items": [
                        {"label": "Video", "action": _script("script.stereo_input_select_video")},
                        {"label": "Turntable", "action": _script("script.stereo_input_select_turntable")},
                        {"label": "Music sync", "action": _script("script.stereo_input_select_music_sync")},
                    ],
                },
            ],
        },
        {
            "id": "music",
            "title": "Music",
            "sections": [
                {"type": "now_playing", "entity": entity}
                for entity in (
                    "media_player.oneplus_speaker_2",
                    "media_player.kitchen",
                    "media_player.house",
                    "media_player.phoster_2",
                )
            ],
        },
    ],
}
