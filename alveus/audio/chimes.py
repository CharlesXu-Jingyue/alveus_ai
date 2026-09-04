from __future__ import annotations

import numpy as np

SR = 24000


def _tone(freqs: list[float], dur: float, vol: float = 0.18) -> np.ndarray:
    t = np.arange(int(SR * dur)) / SR
    env = np.minimum(1.0, np.minimum(t / 0.01, (dur - t) / 0.04))
    parts = [np.sin(2 * np.pi * f * t) for f in freqs]
    return (vol * env * sum(parts) / len(parts)).astype(np.float32)


def listen_chime() -> np.ndarray:
    return np.concatenate([_tone([660], 0.09), _tone([880], 0.12)])


def done_chime() -> np.ndarray:
    return np.concatenate([_tone([880], 0.08), _tone([660], 0.10)])


def error_chime() -> np.ndarray:
    return _tone([330, 340], 0.25)
