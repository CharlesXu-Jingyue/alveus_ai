from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# Languages of Chatterbox Multilingual (ISO 639-1).
MULTILINGUAL_LANGS = ["ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "it", "ja", "ko", "ms",
                      "nl", "no", "pl", "pt", "ru", "sv", "sw", "tr", "zh"]


class ChatterboxTTS:
    """Resemble AI Chatterbox: turbo (English, fastest), standard (English, expressive) or
    multilingual (23 languages incl. Chinese, auto-detected per sentence). Zero-shot voice cloning."""

    name = "chatterbox"
    sample_rate = 24000

    def __init__(self, opts: dict, device: str = "cuda"):
        self.variant = opts.get("model", "turbo")
        self.voice_ref = opts.get("voice_ref") or None
        self.exaggeration = float(opts.get("exaggeration", 0.5))
        self.cfg_weight = float(opts.get("cfg_weight", 0.5))
        self.language = (opts.get("language") or "auto").lower()          # multilingual only
        self.fallback_language = (opts.get("fallback_language") or "en").lower()
        self.device = device
        self._model = None
        self.warning: str | None = None
        if self.voice_ref and not Path(os.path.expanduser(self.voice_ref)).exists():
            self.warning = (f"voice sample not found: {self.voice_ref} — using the built-in voice. "
                            "Fix the path in Settings → Speech → Voice sample to clone.")
            log.error(self.warning)
            self.voice_ref = None
        elif self.voice_ref:
            self.voice_ref = os.path.expanduser(self.voice_ref)

    def load(self) -> None:
        if self._model is not None:
            return
        if self.variant == "turbo":
            from chatterbox.tts_turbo import ChatterboxTurboTTS as M
        elif self.variant == "multilingual":
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS as M
        else:
            from chatterbox.tts import ChatterboxTTS as M
        log.info("Loading Chatterbox %s on %s", self.variant, self.device)
        self._model = M.from_pretrained(device=self.device)
        self.sample_rate = int(getattr(self._model, "sr", 24000))

    def language_for(self, text: str) -> str:
        if self.language != "auto":
            return self.language
        from .langid import detect_language

        return detect_language(text, fallback=self.fallback_language, allowed=set(MULTILINGUAL_LANGS))

    def synthesize(self, text: str) -> np.ndarray:
        self.load()
        from ..agent.sentences import SentenceBuffer, has_speech

        if not has_speech(text):
            return np.zeros(0, dtype=np.float32)
        parts = [text]
        if self.variant == "multilingual" and self.language == "auto":
            # Mixed-language text: voice each sentence in its own language.
            sb = SentenceBuffer(min_chars=1)
            parts = [p for p in sb.feed(text) + sb.flush() if has_speech(p)]
        gap = np.zeros(int(0.12 * self.sample_rate), dtype=np.float32)
        clips: list[np.ndarray] = []
        for part in parts:
            try:
                clips.append(self._synth_one(part))
                clips.append(gap)
            except Exception as e:  # noqa: BLE001  (one bad sentence must not silence the reply)
                log.warning("chatterbox could not voice %r: %s", part[:60], e)
        return np.concatenate(clips[:-1]) if clips else np.zeros(0, dtype=np.float32)

    def _synth_one(self, text: str) -> np.ndarray:
        kw: dict = {}
        if self.voice_ref:
            kw["audio_prompt_path"] = self.voice_ref
        if self.variant == "multilingual":
            kw["language_id"] = self.language_for(text)
            kw.update(exaggeration=self.exaggeration, cfg_weight=self.cfg_weight)
            log.debug("chatterbox multilingual: %s <- %r", kw["language_id"], text[:60])
        elif self.variant != "turbo":
            kw.update(exaggeration=self.exaggeration, cfg_weight=self.cfg_weight)
        wav = self._model.generate(text, **kw)
        a = wav.detach().cpu().numpy() if hasattr(wav, "detach") else np.asarray(wav)
        return a.reshape(-1).astype(np.float32)

    def voices(self) -> list[str]:
        return ["default"] + ([self.voice_ref] if self.voice_ref else [])
