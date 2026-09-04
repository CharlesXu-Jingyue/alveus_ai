from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)


class ChatterboxTTS:
    """Resemble AI Chatterbox (Turbo by default). Supports zero-shot voice cloning."""

    name = "chatterbox"
    sample_rate = 24000

    def __init__(self, opts: dict, device: str = "cuda"):
        self.variant = opts.get("model", "turbo")
        self.voice_ref = opts.get("voice_ref") or None
        self.exaggeration = float(opts.get("exaggeration", 0.5))
        self.cfg_weight = float(opts.get("cfg_weight", 0.5))
        self.device = device
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return
        if self.variant == "turbo":
            from chatterbox.tts_turbo import ChatterboxTurboTTS as M
        else:
            from chatterbox.tts import ChatterboxTTS as M
        log.info("Loading Chatterbox %s on %s", self.variant, self.device)
        self._model = M.from_pretrained(device=self.device)
        self.sample_rate = int(getattr(self._model, "sr", 24000))

    def synthesize(self, text: str) -> np.ndarray:
        self.load()
        kw = {}
        if self.voice_ref:
            kw["audio_prompt_path"] = self.voice_ref
        if self.variant != "turbo":
            kw.update(exaggeration=self.exaggeration, cfg_weight=self.cfg_weight)
        wav = self._model.generate(text, **kw)
        a = wav.detach().cpu().numpy() if hasattr(wav, "detach") else np.asarray(wav)
        return a.reshape(-1).astype(np.float32)

    def voices(self) -> list[str]:
        return ["default"] + ([self.voice_ref] if self.voice_ref else [])
