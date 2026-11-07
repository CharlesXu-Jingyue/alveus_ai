"""Apply a changed configuration to the running assistant, without restarting it.

What happens per change (the conversation is kept in every case):

  instant      names, personality, instructions and voice gender (system prompt rebuilt), language-model settings and
               switching to another profile (a new adapter; for a local model the alveus-llm unit is
               restarted with it), agent limits, voice and speech settings an engine can take in place
               (Kokoro voice / speed / accent, Chatterbox sample / expressiveness / languages, Whisper
               language), listening timing, wake-word names and sensitivity, the keyboard shortcut,
               chimes, interruption, log level
  reload       another voice or speech-recognition engine or model: the new one is loaded first, then
               swapped in, then the old one is freed (a few seconds; nothing is kept loaded in advance)
  restart      tool servers, audio devices, the web server address: reported, applied at the next start
"""
from __future__ import annotations

import asyncio
import gc
import json
import logging
from typing import Any

from .config import engine_opts, llm_profile

log = logging.getLogger(__name__)

# changes that only take effect when the assistant restarts, with the reason shown to the owner
RESTART = (("tools.servers", "tool servers (which tools, folders, coding model)"),
           ("audio.backend", "audio system"), ("audio.input_device", "microphone"),
           ("audio.output_device", "speaker"), ("audio.sample_rate", "audio sample rate"),
           ("api.", "web server address"))


def diff_paths(a: Any, b: Any, prefix: str = "") -> list[str]:
    """Dotted paths of the leaves that differ between two configuration trees (private keys skipped)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        for k in sorted(set(a) | set(b), key=str):
            if str(k).startswith("_"):
                continue
            out += diff_paths(a.get(k), b.get(k), f"{prefix}{k}.")
        return out
    return [] if a == b else [prefix.rstrip(".")]


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _free_gpu() -> None:
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass


async def _engine(assistant, section: str, old, new, report: dict[str, list[str]]) -> None:
    from .stt import make_stt
    from .tts import make_tts
    label = {"tts": "voice", "stt": "speech recognition"}[section]
    cur = getattr(assistant, section)
    o_sec, n_sec = old.get(section) or {}, new.get(section) or {}
    same_engine = o_sec.get("backend") == n_sec.get("backend") and o_sec.get("device") == n_sec.get("device")
    opts = engine_opts(new, section)
    if _same(engine_opts(old, section), opts) and same_engine:
        return
    if same_engine and hasattr(cur, "reconfigure"):
        if cur.reconfigure(opts):
            report["live"].append(f"{label}: new settings in use")
            return
    fresh = (make_tts if section == "tts" else make_stt)(new)
    loaded = getattr(cur, "_model", None) is not None or getattr(cur, "_pipe", None) is not None
    if loaded or getattr(assistant, "load_speech", True):
        try:
            await asyncio.get_running_loop().run_in_executor(None, fresh.load)
        except Exception as e:  # noqa: BLE001 - keep the working engine
            log.exception("could not load the new %s engine", label)
            report["errors"].append(f"{label}: could not load {getattr(fresh, 'name', '?')} ({type(e).__name__}: "
                                    f"{str(e)[:160]}); the previous one stays in use until a restart")
            return
    setattr(assistant, section, fresh)
    del cur
    _free_gpu()
    report["reloaded"].append(f"{label}: {getattr(fresh, 'name', section)} "
                              f"{opts.get('model') or ''}".strip() + " loaded")


async def apply_config(assistant, new) -> dict[str, list[str]]:
    """Bring a running VoiceAssistant / HeadlessAssistant in line with ``new``; returns what happened."""
    old = assistant.cfg
    changed = diff_paths(dict(old), dict(new))
    report: dict[str, list[str]] = {"changed": changed, "live": [], "reloaded": [], "restart": [], "errors": []}
    if not changed:
        return report
    assistant.cfg = new
    loop = asyncio.get_running_loop()

    agent = getattr(assistant, "agent", None)
    if agent is not None:
        agent.cfg = new
        agent.max_rounds = int(new.llm.get("max_tool_rounds", 12))
        agent.max_history = int(new.assistant.get("max_history_turns", 30))
        agent.confirm_destructive = bool(new.tools.get("confirm_destructive", True))
        agent.no_confirm = set(new.tools.get("no_confirm") or [])
        try:
            op, np_ = llm_profile(old), llm_profile(new)
        except KeyError as e:
            report["errors"].append(f"language model: {e}")
            op = np_ = None
        if np_ is not None and not _same(dict(op), dict(np_)):
            from .llm import make_llm
            from .llm.service import reconcile_local_server
            agent.llm = make_llm(np_)
            agent.thinking = np_.get("thinking")
            if hasattr(assistant, "llm"):
                assistant.llm, assistant.prof = agent.llm, np_
            action = await loop.run_in_executor(None, reconcile_local_server, new, np_)
            note = {"restart": " (the local server is loading it, 20–40 s)", "start": " (starting the local server)",
                    "stop": " (local server stopped)"}.get(action or "", "")
            report["live"].append(f"language model: {np_.get('model')}{note}")
        before = agent.system_prompt
        agent.system_prompt = agent._build_system_prompt()
        if "assistant.personality" in changed:
            from .personality import active
            p = active(new)
            report["live"].append(f"personality: {p.label if p else 'none'}")
        elif agent.system_prompt != before:
            report["live"].append("instructions: names and personality updated")

    for section in ("tts", "stt"):
        if any(p == section or p.startswith(section + ".") for p in changed):
            await _engine(assistant, section, old, new, report)

    if hasattr(assistant, "apply_voice_config"):
        assistant.apply_voice_config(old, new, changed, report)

    if any(p.startswith("logging.level") for p in changed):
        logging.getLogger().setLevel(str(new.logging.get("level", "INFO")).upper())
        report["live"].append("log detail")

    report["restart"] = sorted({why for p in changed for pre, why in RESTART if p.startswith(pre)})
    log.info("settings applied: live %s, reloaded %s, at next restart %s, errors %s",
             report["live"], report["reloaded"], report["restart"], report["errors"])
    return report
