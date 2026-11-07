"""Anthropic Messages protocol (``api: anthropic_messages``) through the official ``anthropic`` SDK.

Translation from the neutral conversation (see base.py):
  system messages        -> top-level ``system``
  assistant + tool_calls -> ``text`` and ``tool_use`` content blocks
  consecutive tool msgs  -> one ``user`` message of ``tool_result`` blocks
  tools (OpenAI format)  -> ``{name, description, input_schema}``

Thinking: adaptive (the model decides how much), with ``display: summarized`` so the GUI can show
the reasoning; depth is set with ``effort``. Claude's thinking blocks are signed and bound to the
conversation that produced them, so each assistant message keeps the full content array in
``_replay`` and is sent back exactly as returned (required inside a tool loop, and keeps the
prompt cache warm). The agent drops that data when it trims old turns, because removing earlier
turns would invalidate the signatures; the message is then rebuilt from its text and tool calls.

Prompt caching: top-level ``cache_control`` caches the stable prefix (tools, system prompt, history).
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from .. import credentials
from .base import HealthCache, LLMError, LLMEvent, replay_of

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
_FINISH = {"end_turn": "stop", "stop_sequence": "stop", "pause_turn": "stop", "tool_use": "tool_calls",
           "max_tokens": "length", "refusal": "refusal", "model_context_window_exceeded": "length"}


class AnthropicLLM:
    api = "anthropic_messages"

    def __init__(self, profile):
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover - dependency is in pyproject
            raise LLMError("the anthropic package is not installed: pip install anthropic") from e
        self._sdk = anthropic
        self.profile = profile
        self.name = profile.get("name", "llm")
        self.provider = str(profile.get("provider", "anthropic"))
        self.label = str(profile.get("label") or self.provider)
        self.model = profile["model"]
        self.base_url = profile.get("base_url") or None
        self.remote = bool(profile.get("remote", True))
        self.max_tokens = int(profile.get("max_tokens") or 16000)
        self.effort = profile.get("effort")
        # thinking: None/True = adaptive thinking; False = send no thinking setting (model default:
        # off on older models; current Opus models always think and only take effort)
        self.thinking = profile.get("thinking", None)
        self.thinking_display = profile.get("thinking_display", "summarized")
        self.fallbacks = profile.get("fallbacks")
        self.prompt_cache = bool(profile.get("prompt_cache", True))
        self.temperature = profile.get("temperature")   # only if a profile sets it (older models)
        self.top_p = profile.get("top_p")
        self.extra_body: dict[str, Any] = dict(profile.get("extra_body") or {})
        self.headers: dict[str, str] = {str(k): str(v) for k, v in (profile.get("headers") or {}).items()}
        self._client = None
        self._client_key: str | None = None
        self._health = HealthCache(60.0)

    # ------------------------------------------------------------------ client
    def client(self):
        """SDK client for the current key (rebuilt when the key changes in the GUI). Without a key
        in Alveus' store the SDK resolves credentials itself (ANTHROPIC_API_KEY, `ant auth login`)."""
        key = credentials.api_key_for(self.profile)
        if self._client is None or key != self._client_key:
            self._client = self._sdk.AsyncAnthropic(api_key=key, base_url=self.base_url, max_retries=2,
                                                    timeout=600.0, default_headers=self.headers or None)
            self._client_key = key
        return self._client

    def _no_key(self) -> LLMError:
        env = self.profile.get("api_key_env") or "ANTHROPIC_API_KEY"
        return LLMError(f"no API key for {self.label}: set {env} under Settings, API keys")

    def _error(self, e: Exception) -> LLMError:
        sdk = self._sdk
        if isinstance(e, TypeError) and "authentication" in str(e).lower():
            return self._no_key()   # the SDK found no key, token or `ant auth login` profile
        if isinstance(e, sdk.AuthenticationError):
            env = self.profile.get("api_key_env") or "ANTHROPIC_API_KEY"
            return LLMError(f"{self.label} rejected the API key (set {env} under Settings, API keys)")
        if isinstance(e, sdk.APIStatusError):
            msg = getattr(e, "message", "") or str(e)
            what = {404: "does not know this model", 429: "is rate limiting us", 529: "is overloaded"}.get(
                e.status_code, f"returned HTTP {e.status_code}")
            return LLMError(f"{self.label} {what}: {msg[:300]}")
        if isinstance(e, sdk.APIConnectionError):
            return LLMError(f"cannot reach the {self.label} API ({type(e).__name__})")
        if isinstance(e, sdk.AnthropicError):
            return LLMError(f"{self.label}: {str(e)[:300]}")
        return LLMError(f"{self.label}: {type(e).__name__}: {str(e)[:300]}")

    # ------------------------------------------------------------------ conversion
    def convert(self, messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        """(system prompt, Anthropic messages) from the neutral conversation."""
        system: list[str] = []
        out: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []

        def flush() -> None:
            if results:
                out.append({"role": "user", "content": list(results)})
                results.clear()

        for m in messages:
            role = m.get("role")
            if role == "system":
                system.append(str(m.get("content") or ""))
                continue
            if role == "tool":
                results.append({"type": "tool_result", "tool_use_id": m.get("tool_call_id", ""),
                                "content": str(m.get("content") or "")})
                continue
            flush()
            if role == "user":
                content = m.get("content")
                out.append({"role": "user", "content": content if content not in (None, "") else "(empty message)"})
            elif role == "assistant":
                rep = replay_of(m, self.provider)
                if rep and rep.get("content"):
                    out.append({"role": "assistant", "content": rep["content"]})
                    continue
                blocks: list[dict[str, Any]] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": str(m["content"])})
                for tc in m.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {"_raw": fn.get("arguments")}
                    blocks.append({"type": "tool_use", "id": tc.get("id", ""), "name": fn.get("name", ""),
                                   "input": args if isinstance(args, dict) else {"value": args}})
                if blocks:   # an empty reply would be rejected; skipping it keeps the request valid
                    out.append({"role": "assistant", "content": blocks})
        flush()
        return "\n\n".join(s for s in system if s), out

    @staticmethod
    def convert_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        out = []
        for t in tools or []:
            fn = t.get("function") or t
            out.append({"name": fn["name"], "description": fn.get("description", ""),
                        "input_schema": fn.get("parameters") or {"type": "object", "properties": {}}})
        return out

    def params(self, messages, tools, thinking) -> dict[str, Any]:
        system, msgs = self.convert(messages)
        p: dict[str, Any] = {"model": self.model, "max_tokens": self.max_tokens, "messages": msgs}
        if system:
            p["system"] = system
        if tools:
            # eager_input_streaming is left off: the agent only runs a call once it is complete, and
            # with it the API would stop validating tool input
            p["tools"] = self.convert_tools(tools)
        th = self.thinking if thinking is None else thinking
        if th is not False:
            p["thinking"] = {"type": "adaptive", **({"display": self.thinking_display} if self.thinking_display else {})}
        if self.effort:
            p["output_config"] = {"effort": self.effort}
        if self.prompt_cache:
            p["cache_control"] = {"type": "ephemeral"}
        if self.temperature is not None:
            p["temperature"] = self.temperature
        if self.top_p is not None:
            p["top_p"] = self.top_p
        if self.extra_body:
            p["extra_body"] = self.extra_body
        return p

    # ------------------------------------------------------------------ health
    async def health(self) -> tuple[bool, str]:
        cached = self._health.get()
        if cached:
            return cached
        try:
            await self.client().models.retrieve(self.model, timeout=8)
        except Exception as e:  # noqa: BLE001
            return self._health.put((False, str(self._error(e))))
        return self._health.put((True, f"{self.label} reachable, model {self.model}"))

    # ------------------------------------------------------------------ stream
    def _open(self, params: dict[str, Any]):
        c = self.client()
        if self.fallbacks:
            return c.beta.messages.stream(betas=[FALLBACK_BETA], fallbacks=self.fallbacks, **params)
        return c.messages.stream(**params)

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        thinking: bool | None = None,
    ) -> AsyncIterator[LLMEvent]:
        params = self.params(messages, tools, thinking)
        msg = None
        for attempt in (0, 1):
            started = False
            try:
                async with self._open(params) as s:
                    open_block: str | None = None
                    async for ev in s:
                        if ev.type == "content_block_start":
                            kind = getattr(ev.content_block, "type", "")
                            if kind == "thinking" and open_block == "thinking_done":
                                yield LLMEvent("reasoning", text="\n\n")   # keep separate notes apart
                            open_block = kind
                        elif ev.type == "content_block_delta":
                            d = ev.delta
                            if d.type == "text_delta" and d.text:
                                started = True
                                yield LLMEvent("content", text=d.text)
                            elif d.type == "thinking_delta" and d.thinking:
                                started = True
                                yield LLMEvent("reasoning", text=d.thinking)
                        elif ev.type == "content_block_stop" and open_block == "thinking":
                            open_block = "thinking_done"
                    msg = await s.get_final_message()
                break
            except self._sdk.APIStatusError as e:
                # a model without server-side fallback support rejects the parameter: retry once without
                if (attempt == 0 and not started and self.fallbacks and e.status_code == 400
                        and "fallback" in str(getattr(e, "message", e)).lower()):
                    log.info("%s: model %s does not take fallbacks; retrying without", self.label, self.model)
                    self.fallbacks = None
                    continue
                log.warning("%s error: %s", self.label, e)
                raise self._error(e) from e
            except self._sdk.AnthropicError as e:
                log.warning("%s error: %s", self.label, e)
                raise self._error(e) from e
            except TypeError as e:
                if "authentication" in str(e).lower():
                    raise self._no_key() from e
                raise
        assert msg is not None

        for b in msg.content:
            if b.type == "tool_use":
                yield LLMEvent("tool_call", tool_call={"id": b.id, "name": b.name,
                                                       "arguments": json.dumps(b.input, ensure_ascii=False)})
        finish = _FINISH.get(msg.stop_reason or "", "stop")
        if finish == "refusal":
            cat = getattr(getattr(msg, "stop_details", None), "category", None)
            log.info("%s declined the request (category %s)", self.label, cat)
        u = msg.usage
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
        usage = {"prompt_tokens": (u.input_tokens or 0) + cache_read + cache_write,
                 "completion_tokens": u.output_tokens or 0}
        if cache_read:
            usage["cached_tokens"] = cache_read
        replay = None
        if finish != "refusal":
            replay = {self.provider: {"model": msg.model, "prefix_bound": True,
                                      "content": [b.to_dict(mode="json") for b in msg.content]}}
        self._health.put((True, f"{self.label} answered, model {self.model}"))
        yield LLMEvent("done", finish_reason=finish, usage=usage, replay=replay)
