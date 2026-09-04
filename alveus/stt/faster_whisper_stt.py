from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)


class FasterWhisperSTT:
    name = "faster_whisper"

    def __init__(self, opts: dict, device: str = "cuda"):
        self.model_name = opts.get("model", "large-v3-turbo")
        self.compute_type = opts.get("compute_type", "float16" if device == "cuda" else "int8")
        self.beam_size = int(opts.get("beam_size", 1))
        self.language = opts.get("language") or None
        self.device = device
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return
        try:  # make cuDNN/cuBLAS from the torch wheels visible to ctranslate2
            import torch  # noqa: F401
        except Exception:  # noqa: BLE001
            pass
        from faster_whisper import WhisperModel

        log.info("Loading faster-whisper %s (%s, %s)", self.model_name, self.device, self.compute_type)
        self._model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        self.load()
        if sample_rate != 16000:
            audio = _resample(audio, sample_rate, 16000)
        segments, _info = self._model.transcribe(
            audio.astype(np.float32),
            beam_size=self.beam_size,
            language=self.language,
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        return " ".join(s.text.strip() for s in segments).strip()


def _resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    n = int(round(len(x) * sr_out / sr_in))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
