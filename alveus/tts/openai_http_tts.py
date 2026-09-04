from __future__ import annotations

import io

import numpy as np
import soundfile as sf
from openai import OpenAI


class OpenAIHttpTTS:
    """Any /v1/audio/speech server (Kokoro-FastAPI, openedai-speech, ...)."""

    name = "openai_http"
    sample_rate = 24000

    def __init__(self, opts: dict):
        self.client = OpenAI(base_url=opts.get("base_url"), api_key=opts.get("api_key") or "local")
        self.model = opts.get("model", "kokoro")
        self.voice = opts.get("voice", "af_heart")

    def load(self) -> None:
        return None

    def synthesize(self, text: str) -> np.ndarray:
        r = self.client.audio.speech.create(model=self.model, voice=self.voice, input=text, response_format="wav")
        data, sr = sf.read(io.BytesIO(r.content), dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        self.sample_rate = sr
        return data.astype(np.float32)

    def voices(self) -> list[str]:
        return [self.voice]
