from __future__ import annotations

import io

import numpy as np
import soundfile as sf
from openai import OpenAI


class OpenAIHttpSTT:
    """Any /v1/audio/transcriptions server (whisper.cpp server, speaches, ...)."""

    name = "openai_http"

    def __init__(self, opts: dict):
        self.client = OpenAI(base_url=opts.get("base_url"), api_key=opts.get("api_key") or "local")
        self.model = opts.get("model", "whisper-1")
        self.language = opts.get("language") or None

    def load(self) -> None:
        return None

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        buf = io.BytesIO()
        sf.write(buf, audio.astype(np.float32), sample_rate, format="WAV", subtype="PCM_16")
        buf.seek(0)
        buf.name = "audio.wav"
        kw = {"language": self.language} if self.language else {}
        r = self.client.audio.transcriptions.create(model=self.model, file=buf, **kw)
        return (r.text or "").strip()
