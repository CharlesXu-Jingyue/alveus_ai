"""Speak a streamed reply sentence by sentence.

Used by both the voice loop and the GUI's speak path so "Speak while generating"
(``assistant.streaming_tts``) behaves the same everywhere:

* streaming on: each sentence is synthesized as soon as it is complete and queued for
  playback, so synthesis of sentence N+1 overlaps playback of sentence N and the
  first words are heard while the model is still generating;
* streaming off: the whole reply is synthesized once, after generation finishes.

Timing is logged at INFO ("first audio after 1.8 s, generation done after 6.2 s") so
the behaviour can be checked from the journal.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from concurrent.futures import Executor

from ..agent.sentences import SentenceBuffer, speakable

log = logging.getLogger(__name__)


class StreamSpeaker:
    def __init__(self, tts, audio_out, *, streaming: bool = True, pool: Executor | None = None,
                 on_speaking: Callable[[], None] | None = None,
                 on_error: Callable[[str], None] | None = None) -> None:
        self.tts, self.audio_out, self.streaming, self.pool = tts, audio_out, streaming, pool
        self.on_speaking, self.on_error = on_speaking, on_error
        self._sb = SentenceBuffer()
        self._parts: list[str] = []
        self._q: asyncio.Queue[str | None] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._t0 = time.monotonic()
        self.first_audio_s: float | None = None
        self.sentences = 0
        self._aborted = False

    @property
    def aborted(self) -> bool:
        return self._aborted

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self._t0 = time.monotonic()
        self._task = asyncio.create_task(self._worker())

    async def feed(self, text: str) -> None:
        """Called for every streamed content chunk."""
        self._parts.append(text)
        if self.streaming and not self._aborted:
            for s in self._sb.feed(text):
                await self._q.put(s)

    def abort(self) -> None:
        """Interrupted: drop what has not been spoken yet and cut playback."""
        self._aborted = True
        self._sb = SentenceBuffer()
        dropped, ended = 0, False
        while True:
            try:
                item = self._q.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item is None:
                ended = True      # finish() already queued the end marker: keep it or the worker never exits
            else:
                dropped += 1
        if ended:
            self._q.put_nowait(None)
        self.audio_out.stop()
        log.info("speech: stopped by the user after %.1f s (%d queued sentence(s) dropped)",
                 time.monotonic() - self._t0, dropped)

    async def say(self, text: str) -> None:
        """Speak an out-of-band sentence (e.g. an error) right away."""
        await self._q.put(text)

    async def finish(self) -> None:
        """Generation is over: flush the rest and wait until everything has been synthesized
        and handed to the player (playback itself may still be running)."""
        gen_s = time.monotonic() - self._t0
        if self._aborted:
            pass
        elif self.streaming:
            for s in self._sb.flush():
                await self._q.put(s)
        else:
            await self._q.put("".join(self._parts))
        await self._q.put(None)
        if self._aborted:
            # a synthesis already running cannot be cancelled; let the worker skip the rest in the
            # background rather than make the caller wait for it
            return
        if self._task:
            await self._task
        if self.sentences:
            log.info("speech: %s, first audio after %.1f s, generation done after %.1f s, %d clip(s)",
                     "streaming" if self.streaming else "whole reply", self.first_audio_s or 0.0, gen_s,
                     self.sentences)

    # ------------------------------------------------------------------ worker
    async def _worker(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            s = await self._q.get()
            if s is None:
                return
            s = speakable(s)
            if not s or self._aborted:
                continue
            try:
                audio = await loop.run_in_executor(self.pool, self.tts.synthesize, s)
                if audio is None or len(audio) == 0 or self._aborted:
                    continue   # stopped while this sentence was being synthesized: never play it
                if self.first_audio_s is None:
                    self.first_audio_s = time.monotonic() - self._t0
                self.sentences += 1
                if self.on_speaking:
                    self.on_speaking()
                self.audio_out.play(audio, self.tts.sample_rate)
            except Exception as e:  # noqa: BLE001
                log.error("TTS failed: %s", e)
                if self.on_error:
                    self.on_error(f"{type(e).__name__}: {e}")
