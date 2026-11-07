from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)

KOKORO_VOICES = [
    "af_heart", "af_alloy", "af_aoede", "af_bella", "af_jessica", "af_kore", "af_nicole", "af_nova",
    "af_river", "af_sarah", "af_sky", "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam",
    "am_michael", "am_onyx", "am_puck", "am_santa", "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
]


class KokoroTTS:
    name = "kokoro"
    sample_rate = 24000

    def __init__(self, opts: dict, device: str = "cuda"):
        self.voice = opts.get("voice", "af_heart")
        self.speed = float(opts.get("speed", 1.0))
        # accent follows the voice (af_/am_ American, bf_/bm_ British) unless set explicitly
        self.lang_code = opts.get("lang_code") or (self.voice[:1] if self.voice[:1] in "ab" else "a")
        self.device = device
        self._pipe = None
        self._pipes: dict[str, object] = {}   # other accents, sharing the loaded model (previews)

    def load(self) -> None:
        if self._pipe is not None:
            return
        from kokoro import KPipeline

        log.info("Loading Kokoro (%s, voice %s)", self.device, self.voice)
        self._pipe = KPipeline(lang_code=self.lang_code, repo_id="hexgrad/Kokoro-82M", device=self.device)
        # warm up
        self.synthesize("Ready.")

    def _pipe_for(self, voice: str):
        """The pipeline for a voice's accent; another accent reuses the loaded model (no extra VRAM)."""
        lang = voice[:1] if voice[:1] in "ab" else self.lang_code
        if lang == self.lang_code:
            return self._pipe
        if lang not in self._pipes:
            from kokoro import KPipeline
            self._pipes[lang] = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M", model=self._pipe.model)
        return self._pipes[lang]

    def synthesize(self, text: str, voice: str | None = None) -> np.ndarray:
        """``voice`` overrides the configured voice for this call (GUI preview)."""
        self.load()
        voice = voice or self.voice
        pipe = self._pipe if voice == self.voice else self._pipe_for(voice)
        chunks: list[np.ndarray] = []
        for _gs, _ps, audio in pipe(text, voice=voice, speed=self.speed):
            if audio is None:
                continue
            a = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
            chunks.append(a.astype(np.float32))
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)

    def voices(self) -> list[str]:
        return KOKORO_VOICES
