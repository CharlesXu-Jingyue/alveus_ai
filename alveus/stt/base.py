from __future__ import annotations

from typing import Protocol

import numpy as np


class STTBackend(Protocol):
    name: str

    def load(self) -> None: ...

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """audio: float32 mono in [-1, 1]. Returns transcript text (may be empty)."""
        ...
