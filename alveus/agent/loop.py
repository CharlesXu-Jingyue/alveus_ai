"""The Alveus agent loop: LLM <-> MCP tools, with streamed events for the voice layer."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import platform
import re
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..llm import LLMBackend
from .mcp_client import ToolHub

log = logging.getLogger(__name__)

ConfirmFn = Callable[[str], Awaitable[bool]]


def voice_is_female(cfg) -> bool:
    g = str(cfg.tts.get("voice_gender", "auto")).lower()
    if g in ("female", "f"):
        return True
    if g in ("male", "m"):
        return False
    backend = cfg.tts.get("backend", "kokoro")
    if backend == "kokoro":
        return str((cfg.tts.get("kokoro") or {}).get("voice", "af_heart")).lower().startswith(("af_", "bf_", "ef_", "ff_", "hf_", "if_", "jf_", "pf_", "zf_"))
    if backend == "openai_http":
        return str((cfg.tts.get("openai_http") or {}).get("voice", "")).lower().startswith(("af_", "bf_"))
    return False


def active_names(cfg) -> tuple[str, str]:
    """(name the assistant uses for itself, the other name) based on the voice."""
    a = cfg.assistant
    male, female = a.get("name", "Alveus"), a.get("female_name") or a.get("name", "Alveus")
    return (female, male) if voice_is_female(cfg) else (male, female)


@dataclass
class AgentEvent:
    """kind: content | reasoning | tool_start | tool_result | confirm | done | error"""

    kind: str
    text: str = ""
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)


_DESTRUCTIVE_SHELL = re.compile(
    r"(^|[;&|]\s*)(sudo\s+)?(rm\s|rmdir\s|shred\s|mkfs|dd\s|kill(all)?\s|pkill\s|shutdown|reboot|poweroff|"
    r"systemctl\s+(stop|disable|poweroff|reboot|halt)|git\s+(push\s+--force|reset\s+--hard|clean\s+-f)|"
    r"chmod\s+-R|chown\s+-R|>\s*/dev/sd|truncate\s|:\(\)\s*\{)",
    re.IGNORECASE,
)


class Agent:
    def __init__(
        self,
        llm: LLMBackend,
        hub: ToolHub | None,
        cfg,
        *,
        confirm: ConfirmFn | None = None,
        thinking: bool | None = None,
    ):
        self.llm = llm
        self.hub = hub
        self.cfg = cfg
        self.confirm = confirm
        self.thinking = thinking
        self.max_rounds = int(cfg.llm.get("max_tool_rounds", 12))
        self.max_history = int(cfg.assistant.get("max_history_turns", 30))
        self.confirm_destructive = bool(cfg.tools.get("confirm_destructive", True))
        self.history: list[dict[str, Any]] = []
        self.system_prompt = self._build_system_prompt()
        # one conversation at a time (voice loop, GUI and API share the history)
        self.lock = asyncio.Lock()

    # ------------------------------------------------------------------ prompt
    def _build_system_prompt(self) -> str:
        a = self.cfg.assistant
        persona = "You are {name}, a helpful local voice assistant."
        pf = a.get("persona_file")
        if pf and Path(pf).exists():
            persona = Path(pf).read_text()
        name, other = active_names(self.cfg)
        text = persona.format(
            name=name,
            other_name=other,
            user_name=a.get("user_name", "the user"),
            date=dt.date.today().strftime("%A, %B %d, %Y"),
            hostname=socket.gethostname(),
            os=f"{platform.system()} {platform.release()}",
        )
        if self.hub and self.hub.tools:
            servers = sorted({t.server for t in self.hub.tools.values()})
            text += f"\n\nAvailable tool groups: {', '.join(servers)}."
        return text

    def reset(self) -> None:
        self.history.clear()

    def _trim(self) -> None:
        # keep the last N user turns (and everything after them)
        idx = [i for i, m in enumerate(self.history) if m["role"] == "user"]
        if len(idx) > self.max_history:
            self.history = self.history[idx[-self.max_history]:]

    # ------------------------------------------------------------------ run
    async def run(self, user_text: str, *, thinking: bool | None = None,
                  confirm: ConfirmFn | None = None) -> AsyncIterator[AgentEvent]:
        """Stream events for one user turn. ``confirm`` overrides the default confirmer."""
        confirm = confirm or self.confirm
        self._declined_this_turn = False
        self.history.append({"role": "user", "content": user_text})
        self._trim()
        tools = self.hub.openai_tools() if self.hub else None
        th = self.thinking if thinking is None else thinking

        for round_no in range(self.max_rounds + 1):
            messages = [{"role": "system", "content": self.system_prompt}, *self.history]
            content_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            try:
                async for ev in self.llm.stream(messages, tools, thinking=th):
                    if ev.kind == "content":
                        content_parts.append(ev.text)
                        yield AgentEvent("content", text=ev.text)
                    elif ev.kind == "reasoning":
                        yield AgentEvent("reasoning", text=ev.text)
                    elif ev.kind == "tool_call" and ev.tool_call:
                        tool_calls.append(ev.tool_call)
                    elif ev.kind == "done":
                        yield AgentEvent("done", data={"finish": ev.finish_reason, "usage": ev.usage,
                                                       "round": round_no})
            except Exception as e:
                log.exception("LLM error")
                yield AgentEvent("error", text=f"The language model failed: {e}")
                return

            content = "".join(content_parts)
            if not tool_calls:
                self.history.append({"role": "assistant", "content": content})
                return

            if round_no >= self.max_rounds:
                self.history.append({"role": "assistant", "content": content or "(tool limit reached)"})
                yield AgentEvent("error", text="I reached the tool-call limit for this request.")
                return

            self.history.append({
                "role": "assistant",
                "content": content or None,
                "tool_calls": [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                    for tc in tool_calls
                ],
            })
            for tc in tool_calls:
                try:
                    shown_args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    shown_args = {"_raw": tc["arguments"]}
                yield AgentEvent("tool_start", tool=tc["name"], args=shown_args if isinstance(shown_args, dict) else {})
                result = await self._execute(tc, confirm)
                self.history.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
                yield AgentEvent("tool_result", tool=tc["name"], text=result[:2000])

    async def _execute(self, tc: dict[str, Any], confirm: ConfirmFn | None) -> str:
        name, raw_args = tc["name"], tc["arguments"]
        try:
            args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"arguments were not valid JSON: {e}"})
        if not self.hub:
            return json.dumps({"error": "no tools available"})
        info = self.hub.get(name)
        if info is None:
            return json.dumps({"error": f"unknown tool {name}"})

        if self.confirm_destructive and self._is_destructive(info, args):
            if confirm is None:
                return json.dumps({"cancelled": True, "message": "Destructive action needs user confirmation, "
                                   "but no confirmation channel is available here."})
            if getattr(self, "_declined_this_turn", False):
                return json.dumps({"cancelled": True, "message": "The user already declined a destructive action "
                                   "in this request. Do not retry or work around it; report that it was cancelled."})
            desc = f"{info.name.replace('_', ' ')} with {json.dumps(args)[:200]}"
            ok = await confirm(desc)
            if not ok:
                self._declined_this_turn = True
                return json.dumps({"cancelled": True, "message": "The user declined this action. Do not retry it "
                                   "or attempt it another way; tell the user it was cancelled."})
        return await self.hub.call(name, args)

    @staticmethod
    def _is_destructive(info, args: dict[str, Any]) -> bool:
        if info.destructive:
            return True
        if info.name in ("run_command", "shell", "bash"):
            cmd = str(args.get("command") or args.get("cmd") or "")
            return bool(_DESTRUCTIVE_SHELL.search(cmd))
        return False

    # ------------------------------------------------------------------ helpers
    async def ask(self, user_text: str) -> str:
        """Non-streaming convenience: return the final reply text."""
        parts: list[str] = []
        async for ev in self.run(user_text):
            if ev.kind == "content" or ev.kind == "error":
                parts.append(ev.text)
        return "".join(parts).strip()
