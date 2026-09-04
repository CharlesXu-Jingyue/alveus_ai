"""openWakeWord detector (ONNX runtime). Feeds 80 ms (1280-sample) int16 chunks."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

CHUNK = 1280


class WakeWord:
    def __init__(self, model: str = "hey_jarvis", threshold: float = 0.5, models_dir: str | None = None):
        import openwakeword
        import openwakeword.utils as u
        from openwakeword.model import Model

        self.threshold = threshold
        path = model
        if models_dir and Path(models_dir, f"{model}.onnx").exists():
            path = str(Path(models_dir, f"{model}.onnx"))
        elif not Path(model).exists():
            res = Path(openwakeword.__file__).parent / "resources" / "models"
            if not (res / f"{model}.onnx").exists() or not (res / "melspectrogram.onnx").exists():
                log.info("Downloading openWakeWord model '%s'", model)
                u.download_models(model_names=[model])
        self.model_name = Path(path).stem
        self._m = Model(wakeword_models=[path], inference_framework="onnx")
        self._buf = np.zeros(0, dtype=np.int16)

    def reset(self) -> None:
        self._buf = np.zeros(0, dtype=np.int16)
        try:
            self._m.reset()
        except Exception:  # noqa: BLE001
            pass

    def feed(self, frame_f32: np.ndarray) -> float:
        """Feed any-length float32 frame; returns max score seen for completed 80 ms chunks (0 if none)."""
        pcm = (np.clip(frame_f32, -1, 1) * 32767).astype(np.int16)
        self._buf = np.concatenate([self._buf, pcm])
        best = 0.0
        while len(self._buf) >= CHUNK:
            chunk, self._buf = self._buf[:CHUNK], self._buf[CHUNK:]
            scores = self._m.predict(chunk)
            best = max(best, max(scores.values()) if scores else 0.0)
        return best

    def detected(self, frame_f32: np.ndarray) -> bool:
        return self.feed(frame_f32) >= self.threshold
