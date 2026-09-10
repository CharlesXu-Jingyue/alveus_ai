"""openWakeWord detector (ONNX runtime). Feeds 80 ms (1280-sample) int16 chunks.

Several models can listen at once (``oww_model: [alveus, aurea]`` or ``"alveus, aurea"``); a frame is
detected when any of them scores above the threshold, ``last_model`` says which one."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

CHUNK = 1280


def model_list(value) -> list[str]:
    """``oww_model`` as a list: a YAML list, or a string with comma-separated names. Empty → the default."""
    if isinstance(value, (list, tuple)):
        names = [str(v).strip() for v in value]
    else:
        names = [v.strip() for v in str(value or "").split(",")]
    return [n for n in names if n] or ["hey_jarvis"]


class WakeWord:
    def __init__(self, models="hey_jarvis", threshold: float = 0.5, models_dir: str | None = None):
        import openwakeword
        import openwakeword.utils as u
        from openwakeword.model import Model

        self.threshold = threshold
        paths: list[str] = []
        for model in model_list(models):
            path = model
            if models_dir and Path(models_dir, f"{model}.onnx").exists():
                path = str(Path(models_dir, f"{model}.onnx"))     # custom model (scripts/train_wakeword.sh)
            elif not Path(model).exists():
                res = Path(openwakeword.__file__).parent / "resources" / "models"
                if not (res / f"{model}.onnx").exists() or not (res / "melspectrogram.onnx").exists():
                    log.info("Downloading openWakeWord model '%s'", model)
                    u.download_models(model_names=[model])
            paths.append(path)
        self.model_names = [Path(p).stem for p in paths]
        self.model_name = " / ".join(self.model_names)
        self.last_model: str | None = None       # which model produced the last detection
        self._m = Model(wakeword_models=paths, inference_framework="onnx")
        self._buf = np.zeros(0, dtype=np.int16)

    def phrases(self) -> str:
        """Human wording for the ready message: "'alveus' or 'aurea'"."""
        return " or ".join(f"'{n.replace('_', ' ')}'" for n in self.model_names)

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
            for name, score in scores.items():
                if score > best:
                    best, self.last_model = float(score), str(name)
        return best

    def detected(self, frame_f32: np.ndarray) -> bool:
        return self.feed(frame_f32) >= self.threshold
