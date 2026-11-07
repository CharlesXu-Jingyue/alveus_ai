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

from ..llm import LLMBackend, LLMError
from .mcp_client import ToolHub

log = logging.getLogger(__name__)

# confirm(description) -> bool, or {"ok": bool, "sudo_password": str} when the action needs sudo
ConfirmFn = Callable[[str], Awaitable[Any]]


def voice_is_female(cfg) -> bool:
    """Infer the voice's gender from config.

    auto:  kokoro     -> voice name prefix (af_/bf_ female, am_/bm_ male)
           chatterbox -> the cloned sample's file name must start with f_ or m_
                         (e.g. f_charles_demo.wav); no sample / other name -> not female
           openai_http-> Kokoro-style voice name prefix if present
    """
    from ..config import engine_opts

    opts = engine_opts(cfg, "tts")    # the active engine/model's own gender setting, else tts.voice_gender
    g = str(opts.get("voice_gender") or "auto").lower()
    if g in ("female", "f"):
        return True
    if g in ("male", "m"):
        return False
    backend = cfg.tts.get("backend", "kokoro")
    female_prefixes = ("af_", "bf_", "ef_", "ff_", "hf_", "if_", "jf_", "pf_", "zf_")
    if backend == "kokoro":
        return str(opts.get("voice") or "af_heart").lower().startswith(female_prefixes)
    if backend == "chatterbox":
        stem = Path(str(opts.get("voice_ref") or "")).name.lower()
        return stem.startswith("f_")
    if backend == "openai_http":
        return str(opts.get("voice") or "").lower().startswith(female_prefixes)
    return False


def active_names(cfg) -> tuple[str, str]:
    """(name the assistant uses for itself, the other name) based on the voice."""
    a = cfg.assistant
    male, female = a.get("name", "Alveus"), a.get("female_name") or a.get("name", "Alveus")
    return (female, male) if voice_is_female(cfg) else (male, female)


def describe_action(tool: str, args: dict[str, Any]) -> str:
    """A confirmation question's subject in plain words: "close window: Firefox" rather than
    the JSON arguments (it is spoken aloud and shown on the GUI's Allow/Deny card)."""
    vals = [str(v) for v in args.values() if v not in (None, "", [], {}) and not isinstance(v, bool)]
    text = tool.replace("_", " ") + (": " + ", ".join(vals) if vals else "")
    return text if len(text) <= 160 else text[:157] + "..."


@dataclass
class AgentEvent:
    """kind: content | reasoning | tool_start | tool_result | confirm | done | error"""

    kind: str
    text: str = ""
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)


# any command that escalates privileges is confirmed by the user ("allow once")
_SUDO = re.compile(r"(^|[;&|(]\s*)sudo\s", re.IGNORECASE)
# Tools whose risk depends on the call: asked only when the rule is true (the tool may still be marked
# destructive for other MCP clients). Tools not listed here ask whenever they are marked destructive.
ASK_WHEN = {
    "move_path": lambda a: bool(a.get("overwrite")),                                   # replaces a file
    "control_service": lambda a: str(a.get("action", "")).lower() in ("stop", "disable")
    or str(a.get("scope", "user")).lower() == "system",
}
_DESTRUCTIVE_SHELL = re.compile(
    r"(^|[;&|]\s*)(sudo\s+)?(rm\s|shred\s|mkfs|dd\s|kill(all)?\s|pkill\s|shutdown|reboot|poweroff|"
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
        # risky tools the owner lets run without asking (sudo commands always ask: they need the password)
        self.no_confirm = set(cfg.tools.get("no_confirm") or [])
        self.history: list[dict[str, Any]] = []
        self.system_prompt = self._build_system_prompt()
        # one conversation at a time (voice loop, GUI and API share the history)
        self.lock = asyncio.Lock()
        self._interrupted = False

    def interrupt(self) -> None:
        """Stop the current turn as soon as possible (checked between chunks and tool calls)."""
        self._interrupted = True

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
            voice_gender="female" if voice_is_female(self.cfg) else "male",
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

    def pop_last_turn(self) -> str | None:
        """Remove the last user message and everything after it; return that message's text."""
        idx = [i for i, m in enumerate(self.history) if m["role"] == "user"]
        if not idx:
            return None
        text = self.history[idx[-1]].get("content") or ""
        del self.history[idx[-1]:]
        return text

    def _trim(self) -> None:
        # keep the last N user turns (and everything after them)
        idx = [i for i, m in enumerate(self.history) if m["role"] == "user"]
        if len(idx) > self.max_history:
            self.history = self.history[idx[-self.max_history]:]
            # replay data bound to the old prefix (Claude's signed thinking) is invalid now that the
            # oldest turns are gone; those messages are rebuilt from their text and tool calls
            for m in self.history:
                rep = m.get("_replay")
                if rep:
                    kept = {k: v for k, v in rep.items() if not (isinstance(v, dict) and v.get("prefix_bound"))}
                    if kept:
                        m["_replay"] = kept
                    else:
                        m.pop("_replay")

    # ------------------------------------------------------------------ run
    async def run(self, user_text: str, *, thinking: bool | None = None,
                  confirm: ConfirmFn | None = None) -> AsyncIterator[AgentEvent]:
        """Stream events for one user turn. ``confirm`` overrides the default confirmer."""
        confirm = confirm or self.confirm
        self._declined_this_turn = False
        self._interrupted = False
        self.history.append({"role": "user", "content": user_text})
        self._trim()
        tools = self.hub.openai_tools() if self.hub else None
        th = self.thinking if thinking is None else thinking

        for round_no in range(self.max_rounds + 1):
            messages = [{"role": "system", "content": self.system_prompt}, *self.history]
            content_parts: list[str] = []
            reasoning_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            finish: str | None = None
            replay: dict[str, Any] | None = None
            try:
                stream = self.llm.stream(messages, tools, thinking=th)
                async for ev in stream:
                    if self._interrupted:
                        await stream.aclose()
                        break
                    if ev.kind == "content":
                        content_parts.append(ev.text)
                        yield AgentEvent("content", text=ev.text)
                    elif ev.kind == "reasoning":
                        reasoning_parts.append(ev.text)
                        yield AgentEvent("reasoning", text=ev.text)
                    elif ev.kind == "tool_call" and ev.tool_call:
                        tool_calls.append(ev.tool_call)
                    elif ev.kind == "done":
                        finish, replay = ev.finish_reason, ev.replay
                        yield AgentEvent("done", data={"finish": ev.finish_reason, "usage": ev.usage,
                                                       "round": round_no})
            except LLMError as e:
                log.warning("LLM error: %s", e)
                yield AgentEvent("error", text=f"The language model failed: {e}")
                return
            except Exception as e:
                log.exception("LLM error")
                yield AgentEvent("error", text=f"The language model failed: {e}")
                return

            content = "".join(content_parts)
            # "_reasoning" is kept for the GUI (history view); adapters strip private keys before sending
            # (providers that need the reasoning back, such as DeepSeek, read it from here).
            # "_replay" is the provider's own record of the message (e.g. Claude's signed thinking),
            # sent back verbatim by that provider's adapter only.
            reasoning = "".join(reasoning_parts).strip()
            extra: dict[str, Any] = {"_reasoning": reasoning} if reasoning else {}
            if self._interrupted:
                self.history.append({"role": "assistant", "content": content + " [interrupted by the user]", **extra})
                yield AgentEvent("interrupted", text="Interrupted.")
                return
            if replay:
                extra["_replay"] = replay
            if not tool_calls:
                self.history.append({"role": "assistant", "content": content, **extra})
                if finish == "refusal" and not content.strip():
                    yield AgentEvent("error", text="The model declined to answer that request.")
                elif finish == "length" and not content.strip():
                    yield AgentEvent("error", text="The reply hit the length limit before any answer; "
                                                   "raise Max reply length in the settings.")
                return

            self.history.append({
                "role": "assistant",
                "content": content or None,
                **extra,
                "tool_calls": [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                    for tc in tool_calls
                ],
            })
            stop = None
            if finish == "length":   # cut off mid-arguments: never run a truncated call
                stop = ("Not run: the call was cut off by the output limit.",
                        "My reply hit the length limit in the middle of a tool call; "
                        "raise Max reply length in the settings.")
            elif round_no >= self.max_rounds:
                stop = ("Not run: the tool-call limit for this request was reached.",
                        "I reached the tool-call limit for this request.")
            if stop:
                # answer every call anyway, so the conversation stays valid for providers that require it
                for tc in tool_calls:
                    self.history.append({"role": "tool", "tool_call_id": tc["id"],
                                         "content": json.dumps({"cancelled": True, "message": stop[0]})})
                yield AgentEvent("error", text=stop[1])
                return
            for tc in tool_calls:
                try:
                    shown_args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    shown_args = {"_raw": tc["arguments"]}
                yield AgentEvent("tool_start", tool=tc["name"], args=shown_args if isinstance(shown_args, dict) else {})
                if self._interrupted:
                    result = json.dumps({"cancelled": True, "message": "Interrupted by the user before running."})
                else:
                    result = await self._execute(tc, confirm)
                self.history.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
                yield AgentEvent("tool_result", tool=tc["name"], text=result[:2000])
            if self._interrupted:
                yield AgentEvent("interrupted", text="Interrupted.")
                return

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

        # credentials only ever come from the user's confirmation, never from the model
        args.pop("sudo_password", None)
        sudo = self._needs_sudo(info, args)
        trusted = (info.full_name in self.no_confirm or info.name in self.no_confirm) \
            and info.name not in ("run_command", "shell", "bash")   # shell commands are always checked
        if sudo or (self.confirm_destructive and not trusted and self._is_destructive(info, args)):
            if confirm is None:
                return json.dumps({"cancelled": True, "message": "This action needs user confirmation, "
                                   "but no confirmation channel is available here."})
            if getattr(self, "_declined_this_turn", False):
                return json.dumps({"cancelled": True, "message": "The user already declined an action "
                                   "in this request. Do not retry or work around it; report that it was cancelled."})
            desc = describe_action(info.name, args)
            if sudo:
                desc = "[sudo] " + desc
            ans = await confirm(desc)
            ok = ans.get("ok") if isinstance(ans, dict) else bool(ans)
            if not ok:
                if isinstance(ans, dict) and ans.get("reason") == "no_answer":
                    # no answer = "not now": left undone without counting as a refusal
                    return json.dumps({"cancelled": True, "message": "The user did not answer the confirmation "
                                       "question, so the action was not run. Say in a few words that you left it "
                                       "for now; do not ask again unless the user brings it up."})
                self._declined_this_turn = True
                return json.dumps({"cancelled": True, "message": "The user declined this action. Do not retry it "
                                   "or attempt it another way; tell the user it was cancelled."})
            if sudo and isinstance(ans, dict) and ans.get("sudo_password"):
                args["sudo_password"] = ans["sudo_password"]
        return await self.hub.call(name, args)

    @staticmethod
    def _needs_sudo(info, args: dict[str, Any]) -> bool:
        if info.name in ("run_command", "shell", "bash"):
            return bool(_SUDO.search(str(args.get("command") or args.get("cmd") or "")))
        return False

    @staticmethod
    def _is_destructive(info, args: dict[str, Any]) -> bool:
        if info.name in ASK_WHEN:
            return bool(ASK_WHEN[info.name](args))
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
