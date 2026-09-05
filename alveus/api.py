"""HTTP gateway + browser GUI.

Runs inside `alveus talk` (shares the loaded models, agent, tools and speaker) or standalone via
`alveus api`. Serves the single-page GUI at ``/`` and a JSON/SSE API underneath it.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import subprocess
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import yaml
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from . import __version__
from .config import (REPO_ROOT, load_config, patch_local_yaml, read_local_yaml, write_local_yaml)

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "web"
PERSONA = REPO_ROOT / "config" / "persona.md"
OWW_PRETRAINED = ["hey_jarvis", "alexa", "hey_mycroft", "hey_rhasspy", "weather", "timer"]


# ----------------------------------------------------------------------------- live events
class EventBus:
    """Fan-out of state/transcript events to SSE subscribers (thread-safe publish)."""

    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.state = "idle"
        self.recent: list[dict[str, Any]] = []

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, kind: str, **data: Any) -> None:
        ev = {"type": kind, "t": time.time(), **data}
        if kind == "state":
            self.state = data.get("state", self.state)
        else:
            self.recent = (self.recent + [ev])[-200:]
        if self._loop is None:
            return

        def _push() -> None:
            for q in list(self._subs):
                try:
                    q.put_nowait(ev)
                except asyncio.QueueFull:
                    pass

        try:
            self._loop.call_soon_threadsafe(_push)
        except RuntimeError:
            pass

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs.add(q)
        try:
            yield {"type": "state", "state": self.state, "t": time.time()}
            while True:
                try:
                    yield await asyncio.wait_for(q.get(), timeout=20)
                except TimeoutError:
                    yield {"type": "ping", "t": time.time()}
        finally:
            self._subs.discard(q)


class ConfirmBroker:
    """Routes destructive-action confirmations to a browser session."""

    def __init__(self) -> None:
        self.pending: dict[str, asyncio.Future] = {}

    def make_confirmer(self, emit: Callable[[dict[str, Any]], Awaitable[None]], timeout: float = 120.0):
        async def confirm(description: str) -> bool:
            cid = uuid.uuid4().hex[:10]
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            self.pending[cid] = fut
            await emit({"type": "confirm", "id": cid, "description": description})
            try:
                return bool(await asyncio.wait_for(fut, timeout))
            except TimeoutError:
                return False
            finally:
                self.pending.pop(cid, None)
        return confirm

    def resolve(self, cid: str, ok: bool) -> bool:
        fut = self.pending.get(cid)
        if fut is None or fut.done():
            return False
        fut.set_result(ok)
        return True


def _sse(ev: dict[str, Any]) -> str:
    return f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"


# ----------------------------------------------------------------------------- models
class ChatIn(BaseModel):
    text: str
    speak: bool = False
    reset: bool = False


class SpeakIn(BaseModel):
    text: str
    play: bool = False


class ConfirmIn(BaseModel):
    id: str
    ok: bool


class ConfigIn(BaseModel):
    patch: dict[str, Any] | None = None
    yaml: str | None = None


class PersonaIn(BaseModel):
    text: str


class RestartIn(BaseModel):
    what: str = "assistant"   # assistant | llm | both


class LLMCheckIn(BaseModel):
    profile: str


# ----------------------------------------------------------------------------- app
def build_app(assistant, bus: EventBus | None = None) -> FastAPI:
    """`assistant` is a VoiceAssistant (talk mode) or a HeadlessAssistant (api mode)."""
    app = FastAPI(title="Alveus", version=__version__)
    bus = bus or EventBus()
    broker = ConfirmBroker()
    has_voice = hasattr(assistant, "audio_out")

    @app.on_event("startup")
    async def _bind() -> None:
        bus.bind(asyncio.get_running_loop())

    # ---- GUI
    @app.get("/", include_in_schema=False)
    @app.get("/ui", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html", media_type="text/html")

    @app.get("/handbook", include_in_schema=False)
    async def handbook() -> FileResponse:
        path = REPO_ROOT / "docs" / "handbook.html"
        if not path.exists():
            raise HTTPException(404, "docs/handbook.html not built yet: run scripts/build_handbook.py")
        return FileResponse(path, media_type="text/html")

    # ---- status
    @app.get("/health")
    async def health() -> dict[str, Any]:
        from .agent.loop import active_names
        ok, msg = await assistant.agent.llm.health() if assistant.agent else (False, "agent not ready")
        name, other = active_names(assistant.cfg)
        return {"ok": ok, "llm": msg, "state": bus.state if has_voice else "text-only",
                "tools": len(assistant.hub.tools) if assistant.hub else 0,
                "stt": assistant.stt.name, "tts": assistant.tts.name, "name": name, "other_name": other,
                "voice": has_voice, "version": __version__, "profile": assistant.cfg.llm.profile,
                "managed_by_systemd": bool(os.environ.get("INVOCATION_ID")),
                "llm_service": _unit_status("alveus-llm.service") if os.environ.get("INVOCATION_ID") else None}

    @app.get("/tools")
    async def tools() -> list[dict[str, Any]]:
        return [{"name": t.full_name, "server": t.server, "description": t.description, "destructive": t.destructive}
                for t in (assistant.hub.tools.values() if assistant.hub else [])]

    @app.get("/events")
    async def events() -> StreamingResponse:
        async def gen() -> AsyncIterator[str]:
            async for ev in bus.stream():
                yield _sse(ev)
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---- conversation
    @app.get("/history")
    async def history() -> list[dict[str, Any]]:
        return _normalize_history(assistant.agent.history if assistant.agent else [])

    @app.post("/history/reset")
    async def history_reset() -> dict[str, bool]:
        assistant.agent.reset()
        bus.publish("reset")
        return {"reset": True}

    @app.post("/chat")
    async def chat(inp: ChatIn) -> dict[str, Any]:
        if inp.reset:
            assistant.agent.reset()
        if inp.speak and hasattr(assistant, "respond"):
            reply = await assistant.respond(inp.text)
        else:
            async with assistant.agent.lock:
                reply = await assistant.agent.ask(inp.text)
        bus.publish("transcript", who="user", text=inp.text, source="api")
        bus.publish("transcript", who="assistant", text=reply, source="api")
        return {"reply": reply}

    @app.post("/chat/stream")
    async def chat_stream(inp: ChatIn) -> StreamingResponse:
        q: asyncio.Queue = asyncio.Queue()

        async def emit(ev: dict[str, Any]) -> None:
            await q.put(ev)

        confirm = broker.make_confirmer(emit)

        async def worker() -> None:
            parts: list[str] = []
            try:
                if inp.reset:
                    assistant.agent.reset()
                bus.publish("transcript", who="user", text=inp.text, source="gui")
                async with assistant.agent.lock:
                    if has_voice:
                        bus.publish("state", state="thinking")
                    async for ev in assistant.agent.run(inp.text, confirm=confirm):
                        if ev.kind == "content":
                            parts.append(ev.text)
                            await emit({"type": "content", "text": ev.text})
                        elif ev.kind == "reasoning":
                            await emit({"type": "reasoning", "text": ev.text})
                        elif ev.kind == "tool_start":
                            await emit({"type": "tool_start", "tool": ev.tool, "args": ev.args})
                        elif ev.kind == "tool_result":
                            await emit({"type": "tool_result", "tool": ev.tool, "text": ev.text})
                        elif ev.kind == "error":
                            parts.append(" " + ev.text)
                            await emit({"type": "error", "text": ev.text})
                reply = "".join(parts).strip()
                bus.publish("transcript", who="assistant", text=reply, source="gui")
                if inp.speak and has_voice and reply:
                    from .agent.sentences import speakable
                    loop = asyncio.get_running_loop()
                    audio = await loop.run_in_executor(None, assistant.tts.synthesize, speakable(reply))
                    bus.publish("state", state="speaking")
                    assistant.audio_out.play(audio, assistant.tts.sample_rate)
                    await loop.run_in_executor(None, assistant.audio_out.wait)
                if has_voice:
                    bus.publish("state", state="idle")
                await emit({"type": "done", "reply": reply})
            except Exception as e:  # noqa: BLE001
                log.exception("chat/stream failed")
                await emit({"type": "error", "text": f"{type(e).__name__}: {e}"})
                await emit({"type": "done", "reply": "".join(parts)})
            finally:
                await q.put(None)

        asyncio.create_task(worker())

        async def gen() -> AsyncIterator[str]:
            while True:
                ev = await q.get()
                if ev is None:
                    break
                yield _sse(ev)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/confirm")
    async def confirm(inp: ConfirmIn) -> dict[str, bool]:
        return {"resolved": broker.resolve(inp.id, inp.ok)}

    # ---- speech
    @app.post("/speak")
    async def speak(inp: SpeakIn) -> Response:
        loop = asyncio.get_running_loop()
        audio = await loop.run_in_executor(None, assistant.tts.synthesize, inp.text)
        if inp.play:
            if not has_voice:
                raise HTTPException(409, "no speaker in this mode (run `alveus talk`)")
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
        """Start listening now (used by Wayland keyboard shortcuts / the GUI / other devices)."""
        if hasattr(assistant, "trigger"):
            assistant.trigger.fire()
            return {"triggered": True}
        raise HTTPException(409, "no microphone loop in this mode (run `alveus talk`)")

    @app.post("/stop")
    async def stop() -> dict[str, bool]:
        if has_voice:
            assistant.audio_out.stop()
        return {"stopped": True}

    # ---- configuration
    @app.get("/config")
    async def get_config() -> dict[str, Any]:
        cfg = load_config()
        effective = {k: v for k, v in dict(cfg).items() if not k.startswith("_")}
        local_text = read_local_yaml()
        local = yaml.safe_load(local_text) or {} if local_text.strip() else {}
        from .tts.kokoro_tts import KOKORO_VOICES
        ww_dir = Path(cfg._env["ALVEUS_MODELS"]) / "wakeword"
        custom_oww = sorted(p.stem for p in ww_dir.glob("*.onnx")) if ww_dir.is_dir() else []
        defaults = yaml.safe_load((REPO_ROOT / "config" / "alveus.yaml").read_text()) or {}
        return {
            "effective": effective,
            "defaults": defaults,
            "local": local,
            "local_yaml": local_text,
            "options": {
                "llm_profiles": sorted((cfg.llm.get("profiles") or {}).keys()),
                "stt_backends": ["faster_whisper", "parakeet", "openai_http"],
                "tts_backends": ["kokoro", "chatterbox", "openai_http"],
                "kokoro_voices": KOKORO_VOICES,
                "chatterbox_models": ["turbo", "standard"],
                "voice_genders": ["auto", "female", "male"],
                "parakeet_models": ["nemo-parakeet-tdt-0.6b-v3", "nemo-parakeet-tdt-0.6b-v2", "nemo-parakeet-ctc-0.6b"],
                "whisper_models": ["large-v3-turbo", "large-v3", "distil-large-v3", "medium", "small", "base"],
                "oww_models": OWW_PRETRAINED + custom_oww,
                "activation_modes": ["names", "oww", "both"],
                "hotkey_modes": ["toggle", "hold"],
                "log_levels": ["DEBUG", "INFO", "WARNING"],
                "audio_backends": ["auto", "pipewire", "sounddevice"],
            },
            "paths": {"local_yaml": str(REPO_ROOT / "config" / "local.yaml"), "persona": str(PERSONA),
                      "defaults": str(REPO_ROOT / "config" / "alveus.yaml")},
            "env": dict(cfg._env),
            "managed_by_systemd": bool(os.environ.get("INVOCATION_ID")),
            "running_profile": assistant.cfg.llm.profile,
        }

    @app.put("/config")
    async def put_config(inp: ConfigIn) -> dict[str, Any]:
        try:
            if inp.yaml is not None:
                local = write_local_yaml(inp.yaml)
            elif inp.patch is not None:
                local = patch_local_yaml(inp.patch)
            else:
                raise HTTPException(400, "send {patch: {...}} or {yaml: '...'}")
            load_config()  # validate the merged result parses/expands
        except yaml.YAMLError as e:
            raise HTTPException(400, f"invalid YAML: {e}") from e
        except (ValueError, KeyError) as e:
            raise HTTPException(400, str(e)) from e
        bus.publish("config_saved")
        return {"saved": True, "local": local, "local_yaml": read_local_yaml(), "restart_required": True}

    @app.get("/persona")
    async def get_persona() -> dict[str, str]:
        return {"text": PERSONA.read_text() if PERSONA.exists() else ""}

    @app.put("/persona")
    async def put_persona(inp: PersonaIn) -> dict[str, bool]:
        PERSONA.write_text(inp.text if inp.text.endswith("\n") else inp.text + "\n")
        return {"saved": True, "restart_required": True}

    @app.post("/restart")
    async def restart(inp: RestartIn) -> dict[str, Any]:
        if not os.environ.get("INVOCATION_ID"):
            raise HTTPException(409, "Alveus is not running under systemd. Restart it yourself: stop this "
                                     "process and run `alveus talk` again (or `systemctl --user restart alveus`).")
        units = {"assistant": ["alveus.service"], "llm": ["alveus-llm.service"],
                 "both": ["alveus-llm.service", "alveus.service"]}.get(inp.what)
        if not units:
            raise HTTPException(400, "what must be assistant | llm | both")
        bus.publish("restarting", what=inp.what)
        # detached so the restart survives this process being killed
        subprocess.Popen(["systemctl", "--user", "restart", *units], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"restarting": units}

    @app.get("/services")
    async def services() -> dict[str, Any]:
        return {u: _unit_status(f"{u}.service") for u in ("alveus-llm", "alveus")}

    @app.post("/llm/check")
    async def llm_check(inp: LLMCheckIn) -> dict[str, Any]:
        """Preflight: can the configured server binary load this profile's model file?
        Starts llama-server on a spare port with the weights on the CPU (mmap, no VRAM),
        waits for /health, then stops it. Typically 5-20 s; a bad file fails in <1 s."""
        from .config import llm_profile
        cfg = load_config()
        try:
            prof = llm_profile(cfg, inp.profile)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        serve = prof.get("serve") or {}
        if not serve:
            return {"ok": True, "skipped": "profile has no serve section (external server)"}
        model_path = serve.get("model_path", "")
        if not Path(model_path).exists():
            return {"ok": False, "error": f"model file not found: {model_path}"}
        server_bin = os.path.expanduser(serve.get("command", "llama-server"))
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _probe_model, server_bin, model_path)

    return app


def _probe_model(server_bin: str, model_path: str, timeout: float = 180.0) -> dict[str, Any]:
    import socket

    import httpx

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    cmd = [server_bin, "-m", model_path, "--host", "127.0.0.1", "--port", str(port), "-ngl", "0", "-c", "512",
           "--no-warmup", "--no-webui"]
    t0 = time.time()
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                env={**os.environ, "LLAMA_LOG_COLORS": "0"})
    except FileNotFoundError:
        return {"ok": False, "error": f"server binary not found: {server_bin}"}
    log_lines: list[str] = []
    try:
        while time.time() - t0 < timeout:
            if proc.poll() is not None:
                log_lines = (proc.stdout.read() if proc.stdout else "").splitlines()
                errs = [ln for ln in log_lines if " E " in ln or "error" in ln.lower()]
                return {"ok": False, "seconds": round(time.time() - t0, 1), "model_path": model_path,
                        "error": "\n".join(errs[-6:]) or "\n".join(log_lines[-6:]) or f"exited with code {proc.returncode}"}
            try:
                r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.0)
                if r.status_code == 200:
                    return {"ok": True, "seconds": round(time.time() - t0, 1), "model_path": model_path}
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        return {"ok": False, "error": f"model did not finish loading within {timeout:.0f} s", "model_path": model_path}
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()


def _unit_status(unit: str) -> dict[str, Any]:
    try:
        active = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True, text=True,
                                timeout=5, check=False).stdout.strip()
    except Exception as e:  # noqa: BLE001
        return {"active": "unknown", "error": str(e)}
    out: dict[str, Any] = {"active": active}
    if active != "active":
        try:
            j = subprocess.run(["journalctl", "--user", "-u", unit, "-n", "40", "--no-pager", "-o", "cat"],
                               capture_output=True, text=True, timeout=5, check=False).stdout.splitlines()
            errs = [ln for ln in j if " E " in ln or "error" in ln.lower() or "Failed" in ln]
            out["last_error"] = "\n".join(errs[-4:]) if errs else "\n".join(j[-4:])
        except Exception:  # noqa: BLE001
            pass
    return out


def _normalize_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse raw OpenAI-style messages into GUI turns."""
    out: list[dict[str, Any]] = []
    pending_tools: dict[str, dict[str, Any]] = {}
    for m in history:
        role = m.get("role")
        if role == "user":
            out.append({"role": "user", "text": m.get("content") or ""})
        elif role == "assistant":
            turn = out[-1] if out and out[-1]["role"] == "assistant" and not out[-1].get("final") else None
            if turn is None:
                turn = {"role": "assistant", "text": "", "tools": [], "final": False}
                out.append(turn)
            if m.get("content"):
                turn["text"] = (turn["text"] + "\n" + m["content"]).strip() if turn["text"] else m["content"]
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": fn.get("arguments")}
                rec = {"name": fn.get("name"), "args": args, "result": None}
                turn["tools"].append(rec)
                pending_tools[tc.get("id", "")] = rec
            if not m.get("tool_calls"):
                turn["final"] = True
        elif role == "tool":
            rec = pending_tools.get(m.get("tool_call_id", ""))
            if rec is not None:
                rec["result"] = (m.get("content") or "")[:2000]
    for t in out:
        t.pop("final", None)
    return out


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
