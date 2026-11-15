"""Voice: the assist_satellite fed by the remote's mic over MQTT (voice/start, audio, end, event, stop)."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant.components.assist_pipeline import PipelineEvent, PipelineEventType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

from custom_components.astrion_remote import migrate_voice_key
from custom_components.astrion_remote.const import (
    CONF_BASE_TOPIC,
    CONF_BASE_URL,
    CONF_CONFIG,
    CONF_DEVICE_ID,
    DEFAULT_BASE_URL,
    DOMAIN,
)
from custom_components.astrion_remote.default_config import DEFAULT_CONFIG
from custom_components.astrion_remote.schema import ACTION, validate_config

from .conftest import BASE

SATELLITE = "assist_satellite.astrion_remote"
PIPELINE_PATCH = "homeassistant.components.assist_satellite.entity.async_pipeline_from_audio_stream"
ROOT = Path(__file__).parents[1] / "custom_components" / DOMAIN


def _voice_publishes(mqtt_mock, sub: str) -> list[dict]:
    out = []
    for call in mqtt_mock.async_publish.call_args_list:
        topic, payload, _qos, retain = call.args
        if topic == f"{BASE}/{sub}":
            assert retain is False, f"{topic} must not be retained"
            out.append(json.loads(payload))
    return out


def _start(hass, run: str) -> None:
    async_fire_mqtt_message(hass, f"{BASE}/voice/start", json.dumps({"run": run, "rate": 16000}))


def _audio(hass, run: str, chunk: bytes) -> None:
    async_fire_mqtt_message(hass, f"{BASE}/voice/audio/{run}", chunk)


def _end(hass, run: str, reason: str = "key") -> None:
    async_fire_mqtt_message(hass, f"{BASE}/voice/end", json.dumps({"run": run, "reason": reason}))


class FakePipeline:
    """Stands in for async_pipeline_from_audio_stream; records audio and emits events."""

    def __init__(self, *, vad_after: int | None = None, error: bool = False) -> None:
        self.vad_after = vad_after
        self.error = error
        self.runs: list[dict] = []
        self.release = asyncio.Event()  # set to let a run finish after its audio
        self.release.set()

    async def __call__(self, hass, *, event_callback, stt_stream, **kwargs):
        rec = {"chunks": [], "kwargs": kwargs, "cancelled": False}
        self.runs.append(rec)

        def emit(etype, data=None):
            event_callback(PipelineEvent(etype, data))

        try:
            emit(PipelineEventType.RUN_START, {})
            emit(PipelineEventType.STT_START, {})
            async for chunk in stt_stream:
                rec["chunks"].append(chunk)
                if self.vad_after is not None and len(rec["chunks"]) >= self.vad_after:
                    emit(PipelineEventType.STT_VAD_END, {"timestamp": 1})
                    break
            await self.release.wait()
            if self.error:
                emit(PipelineEventType.ERROR, {"code": "stt-no-text-recognized", "message": "No text recognized"})
                emit(PipelineEventType.RUN_END)
                return
            emit(PipelineEventType.STT_END, {"stt_output": {"text": "turn on the lights"}})
            emit(PipelineEventType.INTENT_START, {})
            emit(
                PipelineEventType.INTENT_END,
                {"intent_output": {"response": {"speech": {"plain": {"speech": "Turned on the lights"}}}}},
            )
            emit(PipelineEventType.TTS_START, {})
            emit(
                PipelineEventType.TTS_END,
                {"tts_output": {"token": "abc.mp3", "url": "/api/tts_proxy/abc.mp3", "mime_type": "audio/mpeg"}},
            )
            emit(PipelineEventType.RUN_END)
        except asyncio.CancelledError:
            rec["cancelled"] = True
            raise


@pytest.fixture
def fake_pipeline():
    fake = FakePipeline()
    with patch(PIPELINE_PATCH, new=fake):
        yield fake


async def test_satellite_entity_created(hass, mqtt_mock, setup_entry):
    """One satellite plus the pipeline/VAD selects, all on the remote's device."""
    state = hass.states.get(SATELLITE)
    assert state is not None
    assert state.state == "idle"
    ent_reg = er.async_get(hass)
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, "ha100"), setup_entry.entry_id)
    sat = ent_reg.async_get(SATELLITE)
    assert sat.device_id == device.id
    assert sat.unique_id == "ha100_assist_satellite"
    pipeline = ent_reg.async_get_entity_id("select", DOMAIN, "ha100-pipeline")
    vad = ent_reg.async_get_entity_id("select", DOMAIN, "ha100-vad_sensitivity")
    assert pipeline and vad
    assert ent_reg.async_get(pipeline).device_id == device.id
    assert hass.states.get(pipeline).state == "preferred"
    # Registered as an Assist device, so it shows in HA's voice assistants UI.
    from homeassistant.components.assist_pipeline.runtime import KEY_ASSIST_PIPELINE

    assert device.id in hass.data[KEY_ASSIST_PIPELINE].pipeline_devices
    # The audio topic is a binary wildcard subscription.
    subs = {c.args[0]: c for c in mqtt_mock.async_subscribe.call_args_list}
    assert f"{BASE}/voice/audio/+" in subs
    assert subs[f"{BASE}/voice/audio/+"].args[3] is None  # encoding=None


async def test_full_run(hass, mqtt_mock, setup_entry, fake_pipeline):
    """start -> audio -> end feeds the pipeline; events map to voice/event (never retained)."""
    mqtt_mock.async_publish.reset_mock()
    _start(hass, "r1")
    await hass.async_block_till_done()
    for i in range(3):
        _audio(hass, "r1", bytes([i]) * 3200)
    await asyncio.sleep(0)
    _end(hass, "r1")
    await hass.async_block_till_done(wait_background_tasks=True)

    assert len(fake_pipeline.runs) == 1
    run = fake_pipeline.runs[0]
    assert run["chunks"] == [bytes([i]) * 3200 for i in range(3)]
    assert run["kwargs"]["satellite_id"] == SATELLITE
    assert run["kwargs"]["tts_audio_output"] == {"preferred_format": "mp3"}

    events = _voice_publishes(mqtt_mock, "voice/event")
    assert events == [
        {"run": "r1", "stage": "listening"},
        {"run": "r1", "stage": "processing", "text": "turn on the lights"},
        {"run": "r1", "stage": "responding", "text": "Turned on the lights"},
        {
            "run": "r1",
            "stage": "responding",
            "text": "Turned on the lights",
            "tts_url": f"{DEFAULT_BASE_URL}/api/tts_proxy/abc.mp3",
        },
        {"run": "r1", "stage": "done"},
    ]
    # The app ended the audio itself: no voice/stop needed.
    assert _voice_publishes(mqtt_mock, "voice/stop") == []
    assert hass.states.get(SATELLITE).state == "idle"


async def test_tts_url_uses_base_url_option(hass, mqtt_mock, fake_pipeline):
    """tts_url = base_url option (trailing slash stripped) + HA's TTS proxy path."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="ha100",
        data={CONF_DEVICE_ID: "ha100", CONF_BASE_TOPIC: BASE},
        options={CONF_CONFIG: validate_config(DEFAULT_CONFIG), CONF_BASE_URL: "http://10.0.0.7:8123/"},
        minor_version=3,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    _start(hass, "u1")
    _audio(hass, "u1", b"\x00" * 3200)
    _end(hass, "u1")
    await hass.async_block_till_done(wait_background_tasks=True)
    urls = [e["tts_url"] for e in _voice_publishes(mqtt_mock, "voice/event") if "tts_url" in e]
    assert urls == ["http://10.0.0.7:8123/api/tts_proxy/abc.mp3"]


async def test_vad_end_publishes_stop(hass, mqtt_mock, setup_entry, fake_pipeline):
    """HA's VAD ends STT -> voice/stop {"run"}; later audio for the run is dropped."""
    fake_pipeline.vad_after = 2
    mqtt_mock.async_publish.reset_mock()
    _start(hass, "v1")
    await hass.async_block_till_done()
    for _ in range(4):
        _audio(hass, "v1", b"\x01" * 3200)
        await asyncio.sleep(0)
    await hass.async_block_till_done()
    assert _voice_publishes(mqtt_mock, "voice/stop") == [{"run": "v1"}]
    _audio(hass, "v1", b"\x02" * 3200)
    _end(hass, "v1", "stop")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert fake_pipeline.runs[0]["chunks"] == [b"\x01" * 3200] * 2
    assert _voice_publishes(mqtt_mock, "voice/stop") == [{"run": "v1"}]
    assert _voice_publishes(mqtt_mock, "voice/event")[-1] == {"run": "v1", "stage": "done"}


async def test_unknown_run_ignored(hass, mqtt_mock, setup_entry, fake_pipeline):
    """Audio/end for a run that was never started (or already finished) changes nothing."""
    mqtt_mock.async_publish.reset_mock()
    _audio(hass, "ghost", b"\x09" * 3200)
    _end(hass, "ghost")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert fake_pipeline.runs == []
    assert _voice_publishes(mqtt_mock, "voice/event") == []

    _start(hass, "k1")
    await hass.async_block_till_done()
    _audio(hass, "ghost", b"\x09" * 3200)
    _audio(hass, "k1", b"\x01" * 3200)
    _end(hass, "ghost")
    await asyncio.sleep(0)
    assert fake_pipeline.runs[0]["chunks"] == [b"\x01" * 3200]
    _end(hass, "k1")
    await hass.async_block_till_done(wait_background_tasks=True)
    # Finished run: late audio is ignored, no second pipeline.
    _audio(hass, "k1", b"\x03" * 3200)
    await hass.async_block_till_done()
    assert len(fake_pipeline.runs) == 1
    assert fake_pipeline.runs[0]["chunks"] == [b"\x01" * 3200]
    # Malformed start: no run.
    async_fire_mqtt_message(hass, f"{BASE}/voice/start", "garbage")
    await hass.async_block_till_done()
    assert len(fake_pipeline.runs) == 1


async def test_new_run_cancels_old(hass, mqtt_mock, setup_entry, fake_pipeline):
    """Only one run at a time: a new voice/start cancels the running one."""
    mqtt_mock.async_publish.reset_mock()
    _start(hass, "a1")
    await hass.async_block_till_done()
    _audio(hass, "a1", b"\x01" * 3200)
    await asyncio.sleep(0)
    _start(hass, "a2")
    _audio(hass, "a1", b"\x0a" * 3200)  # old run: ignored
    _audio(hass, "a2", b"\x02" * 3200)
    _end(hass, "a2")
    # The new run waits (in a background task) for the old one to unwind first.
    await hass.async_block_till_done(wait_background_tasks=True)

    assert fake_pipeline.runs[0]["cancelled"] is True
    assert len(fake_pipeline.runs) == 2
    assert fake_pipeline.runs[0]["chunks"] == [b"\x01" * 3200]
    assert fake_pipeline.runs[1]["chunks"] == [b"\x02" * 3200]
    events = _voice_publishes(mqtt_mock, "voice/event")
    a1 = [e["stage"] for e in events if e["run"] == "a1"]
    a2 = [e["stage"] for e in events if e["run"] == "a2"]
    assert a1 == ["listening"]  # nothing after the cancel
    assert a2 == ["listening", "processing", "responding", "responding", "done"]


async def test_pipeline_error(hass, mqtt_mock, setup_entry, fake_pipeline):
    """A pipeline error becomes stage error with the message; no "done" after it."""
    fake_pipeline.error = True
    mqtt_mock.async_publish.reset_mock()
    _start(hass, "e1")
    _audio(hass, "e1", b"\x01" * 3200)
    _end(hass, "e1")
    await hass.async_block_till_done(wait_background_tasks=True)
    events = _voice_publishes(mqtt_mock, "voice/event")
    assert events == [
        {"run": "e1", "stage": "listening"},
        {"run": "e1", "stage": "error", "error": "No text recognized"},
    ]


async def test_audio_times_out(hass, mqtt_mock, setup_entry, fake_pipeline):
    """No voice/end: the audio stream ends by itself and HA sends voice/stop."""
    mqtt_mock.async_publish.reset_mock()
    with patch("custom_components.astrion_remote.assist_satellite.VOICE_AUDIO_TIMEOUT", 0.05):
        _start(hass, "t1")
        _audio(hass, "t1", b"\x01" * 3200)
        await asyncio.sleep(0.2)
        await hass.async_block_till_done()
    assert fake_pipeline.runs[0]["chunks"] == [b"\x01" * 3200]
    assert _voice_publishes(mqtt_mock, "voice/stop") == [{"run": "t1"}]
    assert _voice_publishes(mqtt_mock, "voice/event")[-1] == {"run": "t1", "stage": "done"}


async def test_bad_rate_refused(hass, mqtt_mock, setup_entry, fake_pipeline):
    """Only 16 kHz audio is accepted."""
    mqtt_mock.async_publish.reset_mock()
    async_fire_mqtt_message(hass, f"{BASE}/voice/start", json.dumps({"run": "b1", "rate": 8000}))
    await hass.async_block_till_done()
    assert fake_pipeline.runs == []
    assert _voice_publishes(mqtt_mock, "voice/event")[0]["stage"] == "error"


async def test_real_pipeline_without_stt_reports_error(hass, mqtt_mock, setup_entry):
    """Unmocked HA pipeline (no STT engine in tests): the remote gets an error, not silence."""
    mqtt_mock.async_publish.reset_mock()
    _start(hass, "n1")
    _audio(hass, "n1", b"\x00" * 3200)
    _end(hass, "n1")
    await hass.async_block_till_done(wait_background_tasks=True)
    events = _voice_publishes(mqtt_mock, "voice/event")
    assert events, "no voice/event published"
    assert events[-1]["run"] == "n1"
    assert events[-1]["stage"] == "error"
    assert events[-1]["error"]


async def test_unload_cancels_run(hass, mqtt_mock, setup_entry, fake_pipeline):
    """Unloading the entry mid-run cancels the pipeline cleanly."""
    _start(hass, "x1")
    _audio(hass, "x1", b"\x01" * 3200)
    await asyncio.sleep(0)
    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert fake_pipeline.runs[0]["cancelled"] is True


# ---- schema, default config, migration, panel ---------------------------------------------------
@pytest.mark.parametrize("target", ["ha", "tv"])
def test_schema_accepts_voice(target):
    assert ACTION({"type": "voice", "target": target}) == {"type": "voice", "target": target}


@pytest.mark.parametrize(
    "action",
    [
        {"type": "voice"},
        {"type": "voice", "target": "google"},
        {"type": "voice", "target": "ha", "key": "SEARCH"},
    ],
)
def test_schema_rejects_bad_voice(action):
    with pytest.raises(vol.Invalid):
        ACTION(action)


def test_default_voice_key():
    config = validate_config(DEFAULT_CONFIG)
    assert config["keys"]["voice"] == {
        "tap": {"type": "voice", "target": "ha"},
        "hold": {"type": "voice", "target": "tv"},
    }
    # Voice actions never add to the call allowlist.
    from custom_components.astrion_remote.schema import compute_allowlist

    assert not [a for a in compute_allowlist(config) if "voice" in a]


def _old_config(voice: dict) -> dict:
    config = validate_config(DEFAULT_CONFIG)
    config["keys"]["voice"] = voice
    return config


OLD_DEFAULT = {"tap": {"type": "tv_key", "key": "SEARCH", "hold": "none"}}


@pytest.mark.parametrize(
    ("voice", "migrated"),
    [
        (OLD_DEFAULT, True),
        ({"tap": {"type": "tv_key", "key": "SEARCH"}}, True),
        ({"tap": {"type": "tv_key", "key": "ASSIST", "hold": "none"}}, False),
        ({**OLD_DEFAULT, "double": {"type": "event"}}, False),
        ({**OLD_DEFAULT, "contexts": {"jamfin": {"tap": {"type": "none"}}}}, False),
        ({"tap": {"type": "voice", "target": "tv"}}, False),
    ],
)
def test_migrate_voice_key_rule(voice, migrated):
    config = _old_config(voice)
    out = migrate_voice_key(config)
    if not migrated:
        assert out is None
        return
    assert out["keys"]["voice"] == DEFAULT_CONFIG["keys"]["voice"]
    assert config["keys"]["voice"] == voice  # input untouched
    assert {k: v for k, v in out["keys"].items() if k != "voice"} == {
        k: v for k, v in config["keys"].items() if k != "voice"
    }


@pytest.mark.parametrize(("voice", "expected"), [(OLD_DEFAULT, None), ({"tap": {"type": "event"}}, "keep")])
async def test_entry_migration(hass, mqtt_mock, voice, expected):
    """A 1.2 entry gets the new voice mapping only if it still had the old default."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="ha100",
        data={CONF_DEVICE_ID: "ha100", CONF_BASE_TOPIC: BASE},
        options={CONF_CONFIG: _old_config(voice), CONF_BASE_URL: DEFAULT_BASE_URL},
        minor_version=2,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 3
    want = voice if expected == "keep" else DEFAULT_CONFIG["keys"]["voice"]
    assert entry.options[CONF_CONFIG]["keys"]["voice"] == want
    assert entry.options[CONF_BASE_URL] == DEFAULT_BASE_URL


def test_panel_js_syntax():
    """The panel still parses after the Voice action was added."""
    node = shutil.which("node") or "/home/isaac/.local/opt/node-v22.23.5-linux-x64/bin/node"
    if not Path(node).exists():
        pytest.skip("node not available")
    js = ROOT / "frontend" / "astrion-panel.js"
    result = subprocess.run([node, "--check", str(js)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    text = js.read_text()
    assert '["voice", "Voice"]' in text
    assert '["ha", "Home Assistant Assist"]' in text and '["tv", "TV Google Assistant"]' in text
    assert 'case "voice":' in text
