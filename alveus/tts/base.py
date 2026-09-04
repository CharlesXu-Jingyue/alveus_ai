from __future__ import annotations

from typing import Protocol

import numpy as np


class TTSBackend(Protocol):
    name: str
    sample_rate: int

    def load(self) -> None: ...

    def synthesize(self, text: str) -> np.ndarray:
        """Return float32 mono audio at ``self.sample_rate``."""
        ...

    def voices(self) -> list[str]: ...
