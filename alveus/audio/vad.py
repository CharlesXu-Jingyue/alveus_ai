"""Silero VAD wrapper operating on 512-sample (32 ms) frames at 16 kHz."""
from __future__ import annotations

import numpy as np


class VAD:
    def __init__(self, threshold: float = 0.5):
        import torch
        from silero_vad import load_silero_vad

        self.threshold = threshold
        self._model = load_silero_vad(onnx=False)
        self._torch = torch
        self.reset()

    def reset(self) -> None:
        try:
            self._model.reset_states()
        except Exception:  # noqa: BLE001
            pass

    def prob(self, frame: np.ndarray) -> float:
        x = self._torch.from_numpy(np.ascontiguousarray(frame, dtype=np.float32))
        with self._torch.no_grad():
            return float(self._model(x, 16000).item())

    def is_speech(self, frame: np.ndarray) -> bool:
        return self.prob(frame) >= self.threshold
