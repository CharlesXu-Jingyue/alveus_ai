from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)


class ParakeetSTT:
    """NVIDIA Parakeet TDT via onnx-asr (ONNX Runtime)."""

    name = "parakeet"

    def __init__(self, opts: dict, device: str = "cuda"):
        self.model_name = opts.get("model", "nemo-parakeet-tdt-0.6b-v3")
        self.device = device
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return
        import onnx_asr

        providers = ["CPUExecutionProvider"]
        if self.device == "cuda":
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        log.info("Loading Parakeet %s (%s)", self.model_name, providers[0])
        try:
            self._model = onnx_asr.load_model(self.model_name, providers=providers)
        except TypeError:
            self._model = onnx_asr.load_model(self.model_name)

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        self.load()
        if sample_rate != 16000:
            from .faster_whisper_stt import _resample
            audio = _resample(audio, sample_rate, 16000)
        res = self._model.recognize(audio.astype(np.float32), sample_rate=16000)
        return (res if isinstance(res, str) else getattr(res, "text", str(res))).strip()
