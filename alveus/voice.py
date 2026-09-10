"""VoiceAssistant: activation (names / wake word / hotkey) -> capture -> STT -> Agent -> streaming TTS."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum

import numpy as np

from .agent import Agent, ToolHub, hub_env
from .agent.loop import active_names
from .agent.sentences import speakable
from .audio.speaker import StreamSpeaker
from .audio import make_audio_in, make_audio_out
from .audio.chimes import SR as CHIME_SR
from .audio.chimes import error_chime, listen_chime
from .audio.hotkey import Hotkey, Trigger
from .audio.names import NameMatcher
from .audio.vad import VAD
from .config import DotDict, llm_profile
from .llm import make_llm
from .stt import make_stt
from .tts import make_tts

log = logging.getLogger(__name__)

YES = {"yes", "yeah", "yep", "sure", "do it", "go ahead", "confirm", "ok", "okay", "affirmative", "please do", "proceed"}
# Whisper hallucinations on near-silence
JUNK = {"thank you.", "thanks for watching.", "you", "bye.", "thank you for watching.", ".", "the end."}


class State(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


class VoiceAssistant:
    def __init__(self, cfg: DotDict, *, on_state: Callable[[State], None] | None = None,
                 on_transcript: Callable[[str, str], None] | None = None,
                 on_event: Callable[..., None] | None = None):
        self.cfg = cfg
        self.on_state = on_state or (lambda s: None)
        self.on_transcript = on_transcript or (lambda who, text: None)
        # live progress of a voice turn for the GUI: assistant_start / assistant_delta / tool_start /
        # tool_result / voice_confirm (kind, **data)
        self.on_event = on_event or (lambda kind, **data: None)
        self.state = State.IDLE
        self.trigger = Trigger()
        self.stop_flag = False
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="alveus")
        self.name, self.other_name = active_names(cfg)

        self.audio_in = make_audio_in(cfg)
        self.audio_out = make_audio_out(cfg)
        self.stt = make_stt(cfg)
        self.tts = make_tts(cfg)
        self.vad = VAD(float(cfg.audio.vad.get("threshold", 0.5)))

        ww = cfg.activation.get("wake_word") or {}
        self.ww_enabled = bool(ww.get("enabled", True))
        self.ww_mode = str(ww.get("mode", "names")) if self.ww_enabled else "off"
        self.names = NameMatcher(list(ww.get("names") or [self.name, self.other_name]), list(ww.get("name_aliases") or []))
        self.name_segment_s = float(ww.get("name_segment_s", 12))
        self.wake = None
        self._wake_hit = False
        if self.ww_mode in ("oww", "both"):
            from .audio.wakeword import WakeWord
            self.wake = WakeWord(ww.get("oww_model", "hey_jarvis"), float(ww.get("threshold", 0.5)),
                                 models_dir=f"{cfg._env['ALVEUS_MODELS']}/wakeword")
        self.hotkey = None
        hk = cfg.activation.get("hotkey") or {}
        if hk.get("enabled", True):
            self.hotkey = Hotkey(hk.get("combo", "<ctrl>+<alt>+<space>"), self.trigger.fire, mode=hk.get("mode", "toggle"))

        self.hub: ToolHub | None = None
        self.agent: Agent | None = None
        self.speaker = None

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        log.info("Loading speech models...")
        loop = asyncio.get_running_loop()
        await asyncio.gather(loop.run_in_executor(self._pool, self.stt.load),
                             loop.run_in_executor(self._pool, self.tts.load))
        prof = llm_profile(self.cfg)
        llm = make_llm(prof)
        ok, msg = await llm.health()
        log.info("LLM %s: %s", "OK" if ok else "NOT READY", msg)
        self.hub = ToolHub(self.cfg.tools.get("servers") or {}, self.cfg._env["ALVEUS_HOME"],
                           env_extra=hub_env(self.cfg))
        await self.hub.connect_all()
        for k, v in self.hub.errors.items():
            log.warning("tool server '%s' unavailable: %s", k, v)
        log.info("Tools: %d (%s)", len(self.hub.tools), ", ".join(sorted({t.server for t in self.hub.tools.values()})))
        self.agent = Agent(llm, self.hub, self.cfg, confirm=self._confirm, thinking=prof.get("thinking"))
        # Listen (hotkey / GUI button / API) while it is thinking or speaking = interrupt, then listen
        self._loop = loop
        self.trigger.on_fire = self._on_trigger
        self.audio_in.start()
        if self.hotkey:
            self.hotkey.start()
        self._set(State.IDLE)
        how = []
        if self.ww_mode in ("names", "both"):
            how.append(f"say '{self.name}' or '{self.other_name}'")
        if self.wake:
            how.append(f"say '{self.wake.model_name.replace('_', ' ')}'")
        if self.hotkey:
            how.append(f"press {self.hotkey.combo}")
        log.info("%s is ready: %s.", self.name, " / ".join(how) or "no activation configured")

    async def close(self) -> None:
        self.stop_flag = True
        self.audio_in.stop()
        self.audio_out.stop()
        if self.hotkey:
            self.hotkey.stop()
        if self.hub:
            await self.hub.close()

    def _set(self, s: State) -> None:
        self.state = s
        self.on_state(s)

    def _on_trigger(self) -> None:
        """Runs on the firing thread: if a reply is in progress, cut it so the loop can listen."""
        if self.state == State.LISTENING or not bool(self.cfg.audio.get("barge_in", True)):
            return   # while recording, the hotkey means "stop recording" (see _record_utterance)
        busy = (self.agent is not None and self.agent.lock.locked()) or self.speaker is not None \
            or self.audio_out.busy
        if busy:   # a voice or GUI turn is generating or speaking
            self._loop.call_soon_threadsafe(self.interrupt)

    def interrupt(self) -> None:
        """Stop the current reply: generation, pending tool calls, queued and playing speech."""
        log.info("interrupt: stopping generation and speech")
        if self.agent is not None:
            self.agent.interrupt()
        if self.speaker is not None:
            self.speaker.abort()
        self.audio_out.stop()

    # ------------------------------------------------------------------ main loop
    async def run_forever(self) -> None:
        await self.start()
        loop = asyncio.get_running_loop()
        follow_up_until = 0.0
        try:
            while not self.stop_flag:
                if self.agent is not None and self.agent.lock.locked():
                    # a GUI/API turn is running: leave the microphone to it (spoken confirmations)
                    # and do not treat its own speech as a wake name; the hotkey still interrupts
                    await asyncio.sleep(0.1)
                    continue
                frame = await loop.run_in_executor(self._pool, self.audio_in.read, 0.2)
                command: str | None = None
                explicit = self.trigger.take()  # hotkey / API trigger

                if not explicit and frame is not None:
                    in_follow_up = time.time() < follow_up_until
                    if self.wake is not None and self.wake.detected(frame):
                        explicit = True
                        self.wake.reset()
                    elif (in_follow_up or self.ww_mode in ("names", "both")) and self.vad.is_speech(frame):
                        # speech started: capture the segment and transcribe it
                        self._set(State.LISTENING if in_follow_up else State.IDLE)
                        seg = await loop.run_in_executor(self._pool, self._record_utterance, [frame], self.name_segment_s, True)
                        if seg is None and not self._wake_hit:
                            continue
                        text = "" if seg is None else await loop.run_in_executor(self._pool, self._transcribe, seg)
                        if self._wake_hit:
                            # the wake-word model fired inside the segment ("hey jarvis" while VAD was
                            # already recording): act like a trigger, drop whatever was transcribed
                            self._wake_hit = False
                            explicit = True
                        elif not text:
                            continue
                        elif in_follow_up:
                            addressed, rest = self.names.match(text)
                            command = rest if addressed else text
                            if addressed and not rest:
                                explicit = True
                        else:
                            addressed, rest = self.names.match(text)
                            if not addressed:
                                log.debug("ignored (not addressed): %s", text)
                                continue
                            log.info("addressed as: %s", text)
                            if rest:
                                command = rest
                            else:
                                explicit = True

                if not explicit and command is None:
                    continue

                follow_up_until = 0.0
                if explicit and command is None:
                    # ---- LISTENING for the actual request
                    self._set(State.LISTENING)
                    if self.cfg.audio.get("chimes", True):
                        self.audio_out.play(listen_chime(), CHIME_SR)
                        await loop.run_in_executor(self._pool, self.audio_out.wait)
                    audio = await loop.run_in_executor(self._pool, self._record_utterance, None, None)
                    if audio is None:
                        self._set(State.IDLE)
                        continue
                    self._set(State.THINKING)
                    command = await loop.run_in_executor(self._pool, self._transcribe, audio)
                    if not command:
                        self._set(State.IDLE)
                        continue

                # ---- THINKING / SPEAKING
                self.on_transcript("user", command)
                await self.respond(command)
                fu = float(self.cfg.activation.wake_word.get("follow_up_window_s", 0) or 0)
                follow_up_until = time.time() + fu if fu > 0 else 0.0
                self.vad.reset()
                self.audio_in.drain()
                self._set(State.IDLE)
        finally:
            await self.close()

    # ------------------------------------------------------------------ pieces
    def _transcribe(self, audio: np.ndarray) -> str:
        text = self.stt.transcribe(audio, 16000).strip()
        if len(text) < 2 or text.lower() in JUNK:
            return ""
        return text

    def _record_utterance(self, prefix: list[np.ndarray] | None, max_len: float | None,
                          watch_wake: bool = False) -> np.ndarray | None:
        """Blocking: capture until end-of-speech silence. Returns float32 16 kHz or None.
        With ``watch_wake`` the frames are also scored by the openWakeWord model (mode ``both``: VAD
        starts recording before the phrase is complete); a detection sets ``self._wake_hit`` and
        returns None so the caller treats it like the hotkey."""
        v = self.cfg.audio.vad
        end_silence = float(v.get("end_silence_ms", 700)) / 1000
        min_speech = float(v.get("min_speech_ms", 250)) / 1000
        max_len = max_len or float(v.get("max_utterance_s", 60))
        no_speech_timeout = 6.0
        frames: list[np.ndarray] = list(prefix or [])
        if not frames:
            self.vad.reset()
            self.audio_in.drain()
        t0 = time.time()
        speech_started = bool(frames)
        speech_dur = sum(len(f) for f in frames) / 16000
        last_speech = time.time()
        while True:
            f = self.audio_in.read(1.0)
            now = time.time()
            if f is None:
                if now - t0 > no_speech_timeout:
                    return None
                continue
            frames.append(f)
            if watch_wake and self.wake is not None and self.wake.detected(f):
                log.info("wake word '%s' detected", self.wake.model_name)
                self.wake.reset()
                self._wake_hit = True
                return None
            if self.vad.is_speech(f):
                speech_started = True
                speech_dur += len(f) / 16000
                last_speech = now
            if not speech_started and now - t0 > no_speech_timeout:
                return None
            if speech_started and now - last_speech > end_silence:
                break
            if now - t0 > max_len:
                break
            if self.trigger.take():  # hotkey pressed again = stop now
                break
        if speech_dur < min_speech:
            return None
        return np.concatenate(frames)

    async def respond(self, text: str) -> str:
        """Run the agent on ``text`` and speak the reply as it streams. Returns the full reply."""
        assert self.agent is not None
        self._set(State.THINKING)
        reply_parts: list[str] = []
        speaker = StreamSpeaker(self.tts, self.audio_out, pool=self._pool,
                                streaming=bool(self.cfg.assistant.get("streaming_tts", True)),
                                on_speaking=lambda: self._set(State.SPEAKING))
        speaker.start()
        self.speaker = speaker   # /stop aborts it
        self.on_event("assistant_start")
        try:
            async with self.agent.lock:
                async for ev in self.agent.run(text):
                    if ev.kind == "content":
                        reply_parts.append(ev.text)
                        self.on_event("assistant_delta", text=ev.text)
                        await speaker.feed(ev.text)
                    elif ev.kind == "tool_start":
                        self.on_event("tool_start", tool=ev.tool, args=ev.args)
                    elif ev.kind == "tool_result":
                        log.info("tool %s -> %s", ev.tool, ev.text[:160].replace("\n", " "))
                        self.on_event("tool_result", tool=ev.tool, text=ev.text)
                    elif ev.kind == "error":
                        reply_parts.append(" " + ev.text)
                        self.on_event("assistant_delta", text=" " + ev.text)
                        await speaker.say(ev.text)
                    elif ev.kind == "interrupted":
                        speaker.abort()
                        self.on_event("assistant_delta", text=" [interrupted]")
        finally:
            await speaker.finish()
            self.speaker = None
        reply = "".join(reply_parts).strip()
        self.on_transcript("assistant", reply)
        if not speaker.aborted:
            await self._wait_playback()
        return reply

    async def _wait_playback(self) -> None:
        """Wait for speech output; the hotkey or the openWakeWord model can interrupt it."""
        loop = asyncio.get_running_loop()
        barge = bool(self.cfg.audio.get("barge_in", True))
        self.audio_in.drain()
        while self.audio_out.busy:
            frame = await loop.run_in_executor(self._pool, self.audio_in.read, 0.1)
            if barge and self.trigger.take():
                log.info("barge-in (hotkey): stopping playback")
                self.audio_out.stop()
                self.trigger.fire()
                break
            if barge and self.wake is not None and frame is not None and self.wake.detected(frame):
                log.info("barge-in (wake word): stopping playback")
                self.wake.reset()
                self.interrupt()
                self.trigger.fire()
                break

    async def _confirm(self, description: str):
        """Spoken confirmation for destructive tool calls. A sudo command needs a typed password, so it
        is handed to the browser GUI (set by the API layer) and the user is told to look there."""
        loop = asyncio.get_running_loop()
        gui = getattr(self, "gui_confirm", None)
        if description.startswith("[sudo]") and gui is not None:
            note = "This needs your administrator password. Please allow it in the browser."
            self.on_event("voice_confirm", text=note)
            audio = await loop.run_in_executor(self._pool, self.tts.synthesize, speakable(note))
            self._set(State.SPEAKING)
            self.audio_out.play(audio, self.tts.sample_rate)
            self._set(State.THINKING)
            return await gui(description)
        prompt = f"I am about to {description.removeprefix('[sudo] ')}. Should I go ahead?"
        self.on_event("voice_confirm", text=prompt)
        audio = await loop.run_in_executor(self._pool, self.tts.synthesize, speakable(prompt))
        self._set(State.SPEAKING)
        self.audio_out.play(audio, self.tts.sample_rate)
        await loop.run_in_executor(self._pool, self.audio_out.wait)
        self._set(State.LISTENING)
        rec = await loop.run_in_executor(self._pool, self._record_utterance, None, 10.0)
        if rec is None:
            return False
        ans = (await loop.run_in_executor(self._pool, self.stt.transcribe, rec, 16000)).lower().strip(" .!,")
        self.on_transcript("user", ans)
        ok = any(ans == y or ans.startswith(y + " ") or ans.startswith(y + ",") for y in YES)
        self._set(State.THINKING)
        return ok

    # helpers for API / CLI
    def speak(self, text: str) -> None:
        self.audio_out.play(self.tts.synthesize(speakable(text)), self.tts.sample_rate)

    def error(self) -> None:
        self.audio_out.play(error_chime(), CHIME_SR)
