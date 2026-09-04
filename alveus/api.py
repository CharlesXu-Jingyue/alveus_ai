"""Optional HTTP gateway: text chat, transcription, speech and a trigger endpoint.

Runs inside `alveus talk` (shares the loaded models) or standalone via `alveus api`.
"""
from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

log = logging.getLogger(__name__)


class ChatIn(BaseModel):
    text: str
    speak: bool = False
    reset: bool = False


class SpeakIn(BaseModel):
    text: str
    play: bool = False


def build_app(assistant) -> FastAPI:
    """`assistant` is a VoiceAssistant (talk mode) or a HeadlessAssistant (api mode)."""
    app = FastAPI(title="Alveus", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        ok, msg = await assistant.agent.llm.health() if assistant.agent else (False, "agent not ready")
        return {"ok": ok, "llm": msg, "state": getattr(assistant, "state", "n/a"),
                "tools": len(assistant.hub.tools) if assistant.hub else 0,
                "stt": assistant.stt.name, "tts": assistant.tts.name}

    @app.get("/tools")
    async def tools() -> list[dict[str, Any]]:
        return [{"name": t.full_name, "description": t.description, "destructive": t.destructive}
                for t in (assistant.hub.tools.values() if assistant.hub else [])]

    @app.post("/chat")
    async def chat(inp: ChatIn) -> dict[str, Any]:
        if inp.reset:
            assistant.agent.reset()
        if inp.speak and hasattr(assistant, "respond"):
            reply = await assistant.respond(inp.text)
        else:
            reply = await assistant.agent.ask(inp.text)
        return {"reply": reply}

    @app.post("/speak")
    async def speak(inp: SpeakIn) -> Response:
        loop = asyncio.get_running_loop()
        audio = await loop.run_in_executor(None, assistant.tts.synthesize, inp.text)
        if inp.play and hasattr(assistant, "audio_out"):
            assistant.audio_out.play(audio, assistant.tts.sample_rate)
            return JSONResponse({"played": True, "seconds": len(audio) / assistant.tts.sample_rate})
        buf = io.BytesIO()
        sf.write(buf, audio, assistant.tts.sample_rate, format="WAV", subtype="PCM_16")
        return Response(buf.getvalue(), media_type="audio/wav")

    @app.post("/transcribe")
    async def transcribe(file: UploadFile = File(...)) -> dict[str, str]:
        data, sr = sf.read(io.BytesIO(await file.read()), dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, assistant.stt.transcribe, np.asarray(data), int(sr))
        return {"text": text}

    @app.post("/trigger")
    async def trigger() -> dict[str, bool]:
        """Start listening now (used by Wayland keyboard shortcuts / other devices)."""
        if hasattr(assistant, "trigger"):
            assistant.trigger.fire()
            return {"triggered": True}
        return {"triggered": False}

    @app.post("/stop")
    async def stop() -> dict[str, bool]:
        if hasattr(assistant, "audio_out"):
            assistant.audio_out.stop()
        return {"stopped": True}

    return app


async def serve(app: FastAPI, host: str, port: int) -> None:
    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level="warning", loop="asyncio")
    server = uvicorn.Server(config)
    await server.serve()


class HeadlessAssistant:
    """Agent + STT + TTS without microphone loop (for `alveus api` / `alveus chat`)."""

    def __init__(self, cfg, *, load_speech: bool = True):
        from .agent import Agent, ToolHub
        from .config import llm_profile
        from .llm import make_llm
        from .stt import make_stt
        from .tts import make_tts

        self.cfg = cfg
        self.prof = llm_profile(cfg)
        self.llm = make_llm(self.prof)
        self.stt = make_stt(cfg)
        self.tts = make_tts(cfg)
        self.load_speech = load_speech
        self.hub: ToolHub | None = None
        self.agent: Agent | None = None
        self._Agent, self._ToolHub = Agent, ToolHub

    async def start(self, confirm=None) -> None:
        self.hub = self._ToolHub(self.cfg.tools.get("servers") or {}, self.cfg._env["ALVEUS_HOME"],
                                 env_extra={"ALVEUS_HOME": self.cfg._env["ALVEUS_HOME"]})
        await self.hub.connect_all()
        self.agent = self._Agent(self.llm, self.hub, self.cfg, confirm=confirm, thinking=self.prof.get("thinking"))
        if self.load_speech:
            loop = asyncio.get_running_loop()
            await asyncio.gather(loop.run_in_executor(None, self.stt.load), loop.run_in_executor(None, self.tts.load))

    async def close(self) -> None:
        if self.hub:
            await self.hub.close()
