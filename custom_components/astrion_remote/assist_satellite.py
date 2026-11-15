"""Assist satellite: HA Assist runs fed by the remote's microphone over MQTT.

Wire format ("Voice" in docs/ARCHITECTURE.md): the app publishes voice/start {"run","rate"},
binary PCM16 mono 16 kHz chunks on voice/audio/<run>, then voice/end {"run"}. We feed the audio
into the pipeline chosen in HA's voice UI and answer on voice/event (and voice/stop at VAD end).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from homeassistant.components import tts
from homeassistant.components.assist_pipeline import (
    PipelineEvent,
    PipelineEventType,
    PipelineStage,
)
from homeassistant.components.assist_satellite import (
    AssistSatelliteConfiguration,
    AssistSatelliteEntity,
    AssistSatelliteEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.network import NoURLAvailableError, get_url

from . import AstrionConfigEntry
from .const import DEFAULT_BASE_URL, DOMAIN, VOICE_AUDIO_TIMEOUT
from .entity import AstrionEntity
from .hub import AstrionHub

_LOGGER = logging.getLogger(__name__)

# ~10 s of 100 ms chunks; anything beyond is dropped (the stream ends at VOICE_AUDIO_TIMEOUT anyway).
_MAX_QUEUED_CHUNKS = 120


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AstrionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the satellite."""
    async_add_entities([AstrionAssistSatellite(entry.runtime_data)])


@dataclass
class _Run:
    """One voice run, from voice/start to the pipeline's end."""

    run_id: str
    queue: asyncio.Queue[bytes | None] = field(default_factory=asyncio.Queue)
    task: asyncio.Task[None] | None = None
    audio_done: bool = False  # voice/end, VAD end, timeout or cancel: no more audio accepted
    cancelled: bool = False  # replaced by a newer run: publish nothing more
    ended: bool = False  # "done" or "error" published
    speech: str | None = None


class AstrionAssistSatellite(AstrionEntity, AssistSatelliteEntity):
    """The remote as an Assist satellite (push to talk; no wake word)."""

    entity_description = AssistSatelliteEntityDescription(key="assist_satellite")
    _attr_name = None

    def __init__(self, hub: AstrionHub) -> None:
        AstrionEntity.__init__(self, hub, "assist_satellite")
        self._run: _Run | None = None  # run that receives audio
        self._active: _Run | None = None  # run whose pipeline events we are handling

    # ---- entity -------------------------------------------------------------------------------
    @property
    def available(self) -> bool:
        """Unavailable while the remote reports offline."""
        return self.hub.online is not False

    @property
    def tts_options(self) -> dict[str, Any] | None:
        """Android 8.1 MediaPlayer plays mp3; HA converts the engine's output if needed."""
        return {tts.ATTR_PREFERRED_FORMAT: "mp3"}

    @property
    def pipeline_entity_id(self) -> str | None:
        """The "Assistant" select on the same device."""
        return er.async_get(self.hass).async_get_entity_id("select", DOMAIN, f"{self.hub.remote_id}-pipeline")

    @property
    def vad_sensitivity_entity_id(self) -> str | None:
        """The "Finished speaking detection" select on the same device."""
        return er.async_get(self.hass).async_get_entity_id(
            "select", DOMAIN, f"{self.hub.remote_id}-vad_sensitivity"
        )

    async def async_added_to_hass(self) -> None:
        """Receive voice messages from the hub."""
        await super().async_added_to_hass()
        self.hub.satellite = self

    async def async_will_remove_from_hass(self) -> None:
        """Stop the current run."""
        if self.hub.satellite is self:
            self.hub.satellite = None
        if (run := self._run) is not None:
            self._cancel(run)
            if run.task is not None:
                await asyncio.wait([run.task])
        await super().async_will_remove_from_hass()

    @callback
    def async_get_configuration(self) -> AssistSatelliteConfiguration:
        """No wake words: the remote is push to talk."""
        return AssistSatelliteConfiguration(available_wake_words=[], active_wake_words=[], max_active_wake_words=0)

    async def async_set_configuration(self, config: AssistSatelliteConfiguration) -> None:
        """Nothing to configure on the remote."""

    # ---- MQTT side (called by the hub) -----------------------------------------------------
    @callback
    def voice_start(self, run: str, rate: int) -> None:
        """voice/start: begin a run; a newer run replaces (cancels) the previous one."""
        previous = self._run
        if previous is not None:
            if previous.run_id == run:
                return  # duplicate start
            self._cancel(previous)
        new = _Run(run)
        self._run = new
        new.task = self.hub.entry.async_create_background_task(
            self.hass,
            self._async_pipeline(new, previous.task if previous else None),
            f"{DOMAIN}_voice_{run}",
        )

    @callback
    def voice_audio(self, run: str, chunk: bytes) -> None:
        """voice/audio/<run>: queue a chunk (unknown or finished runs are ignored)."""
        cur = self._run
        if cur is None or cur.run_id != run or cur.audio_done:
            return
        if cur.queue.qsize() >= _MAX_QUEUED_CHUNKS:
            return
        cur.queue.put_nowait(chunk)

    @callback
    def voice_end(self, run: str) -> None:
        """voice/end: the app stopped recording."""
        cur = self._run
        if cur is None or cur.run_id != run:
            return
        self._end_audio(cur)

    # ---- pipeline ---------------------------------------------------------------------------
    @staticmethod
    def _end_audio(run: _Run) -> None:
        if not run.audio_done:
            run.audio_done = True
            run.queue.put_nowait(None)

    def _cancel(self, run: _Run) -> None:
        run.cancelled = True
        self._end_audio(run)
        if run.task is not None:
            run.task.cancel()
        if self._run is run:
            self._run = None

    async def _audio_stream(self, run: _Run) -> AsyncIterator[bytes]:
        """Chunks until voice/end, or VOICE_AUDIO_TIMEOUT seconds after voice/start."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + VOICE_AUDIO_TIMEOUT
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                chunk = await asyncio.wait_for(run.queue.get(), remaining)
            except TimeoutError:
                _LOGGER.debug("Astrion voice run %s: no voice/end within %ss", run.run_id, VOICE_AUDIO_TIMEOUT)
                break
            if chunk is None:
                break
            yield chunk
        self._stop_audio(run)

    async def _async_pipeline(self, run: _Run, previous: asyncio.Task[None] | None) -> None:
        if previous is not None and not previous.done():
            # Let the old run unwind first so its cleanup cannot touch the new pipeline.
            await asyncio.wait([previous])
        self._active = run
        try:
            await self.async_accept_pipeline_from_satellite(
                self._audio_stream(run), start_stage=PipelineStage.STT, end_stage=PipelineStage.TTS
            )
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001 - report every failure to the remote
            _LOGGER.warning("Astrion voice run %s failed: %s", run.run_id, err)
            self._publish_end(run, "error", error=str(err) or type(err).__name__)
        finally:
            self._end_audio(run)
            if self._active is run:
                self._active = None
            if self._run is run:
                self._run = None
        # Pipeline returned without RUN_END (e.g. intercepted): still tell the app it is over.
        self._publish_end(run, "done")

    def _stop_audio(self, run: _Run) -> None:
        """HA is done listening before the app is: voice/stop (once), then drop further audio."""
        if run.audio_done:
            return
        self._end_audio(run)
        if not run.cancelled:
            self.hub.voice_stop(run.run_id)

    def _publish(self, run: _Run, stage: str, **fields: Any) -> None:
        if not run.cancelled and not run.ended:
            self.hub.voice_event(run.run_id, stage, **fields)

    def _publish_end(self, run: _Run, stage: str, **fields: Any) -> None:
        self._publish(run, stage, **fields)
        run.ended = True

    def _tts_url(self, url: str) -> str:
        """Absolute URL the remote can fetch: base_url option (or HA's internal URL) + path."""
        if url.startswith(("http://", "https://")):
            return url
        base = self.hub.base_url
        if not base:
            try:
                base = get_url(self.hass, prefer_external=False, allow_cloud=False)
            except NoURLAvailableError:
                base = DEFAULT_BASE_URL
        return base.rstrip("/") + url

    @callback
    def on_pipeline_event(self, event: PipelineEvent) -> None:
        """Map pipeline events to voice/event stages."""
        run = self._active
        if run is None:
            return
        data = event.data or {}
        etype = event.type
        if etype is PipelineEventType.STT_START:
            self._publish(run, "listening")
        elif etype is PipelineEventType.STT_VAD_END:
            self._stop_audio(run)
        elif etype is PipelineEventType.STT_END:
            self._stop_audio(run)  # STT is done with the audio either way
            text = (data.get("stt_output") or {}).get("text")
            self._publish(run, "processing", text=text or None)
        elif etype is PipelineEventType.INTENT_END:
            run.speech = _speech(data.get("intent_output")) or None
            self._publish(run, "responding", text=run.speech)
        elif etype is PipelineEventType.TTS_END:
            url = (data.get("tts_output") or {}).get("url")
            if url:
                self._publish(run, "responding", text=run.speech, tts_url=self._tts_url(url))
        elif etype is PipelineEventType.ERROR:
            self._stop_audio(run)
            self._publish_end(run, "error", error=data.get("message") or data.get("code") or "error")
        elif etype is PipelineEventType.RUN_END:
            self._publish_end(run, "done")
            # The remote plays the reply on its own; HA's state should not hang in "responding".
            if self.state == "responding":
                self.tts_response_finished()


def _speech(intent_output: Any) -> str | None:
    """Plain speech of a conversation result (intent-end event data)."""
    try:
        speech = intent_output["response"]["speech"]["plain"]["speech"]
    except (KeyError, TypeError):
        return None
    return speech if isinstance(speech, str) else None
