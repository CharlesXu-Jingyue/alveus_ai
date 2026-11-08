"""OpenAI Chat Completions protocol (``api: openai_chat``).

Serves llama-server, vLLM, SGLang, Ollama, LM Studio and the cloud APIs that copy this protocol
(DeepSeek, OpenRouter, Groq, Together, Mistral, ...). Streams /chat/completions over SSE with plain
httpx, accumulates tool-call fragments by index and reads ``reasoning_content`` (llama.cpp,
DeepSeek) or ``reasoning`` (vLLM, OpenRouter).
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from .. import credentials
from .base import HealthCache, LLMError, LLMEvent, public
from .http import auth_headers, http_error, iter_sse, new_client, normalize_args, open_stream

log = logging.getLogger(__name__)

_FINISH = {"stop": "stop", "tool_calls": "tool_calls", "function_call": "tool_calls", "length": "length",
           "content_filter": "refusal"}


class OpenAICompatLLM:
    api = "openai_chat"

    def __init__(self, profile):
        self.profile = profile
        self.name = profile.get("name", "llm")
        self.provider = str(profile.get("provider", "openai_compat"))
        self.label = str(profile.get("label") or self.provider)
        self.model = profile["model"]
        self.base_url = str(profile.get("base_url") or "").rstrip("/")
        if not self.base_url:
            raise ValueError(f"LLM profile '{self.name}': base_url is required for provider {self.provider}")
        self.remote = bool(profile.get("remote", False))
        self.temperature = profile.get("temperature")
        self.top_p = profile.get("top_p")
        self.max_tokens = profile.get("max_tokens")
        self.max_tokens_field = profile.get("max_tokens_field") or "max_tokens"
        self.effort = profile.get("effort")
        self.extra_body: dict[str, Any] = dict(profile.get("extra_body") or {})
        self.headers: dict[str, Any] = dict(profile.get("headers") or {})
        # thinking: True/False forces it on/off (how: thinking_param); None = the model's default
        self.thinking = profile.get("thinking", None)
        self.thinking_param = profile.get("thinking_param") or "chat_template_kwargs"
        self.reasoning_replay = profile.get("reasoning_replay") or "none"
        self._client = new_client()
        self._health = HealthCache(60.0 if self.remote else 0.0)

    # ------------------------------------------------------------------ helpers
    def _key(self) -> str | None:
        key = credentials.api_key_for(self.profile)
        if not key and self.remote:
            env = self.profile.get("api_key_env") or "an api_key"
            raise LLMError(f"no API key for {self.label}: set {env} under Settings, API keys")
        return key

    def _messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for m in messages:
            msg = public(m)
            if self.reasoning_replay == "all" and m.get("role") == "assistant":
                msg["reasoning_content"] = m.get("_reasoning") or ""
            out.append(msg)
        return out

    def _payload(self, messages, tools, thinking) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            # private bookkeeping keys such as "_reasoning" (GUI) are never sent as such
            "messages": self._messages(messages),
            "stream": True,
            "stream_options": {"include_usage": True},
            **self.extra_body,
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.top_p is not None:
            body["top_p"] = self.top_p
        if self.max_tokens is not None:
            body[self.max_tokens_field] = self.max_tokens
        if self.effort:
            body["reasoning_effort"] = self.effort
        th = self.thinking if thinking is None else thinking
        if th is not None:
            if self.thinking_param == "chat_template_kwargs":
                kw = dict(body.get("chat_template_kwargs") or {})
                kw["enable_thinking"] = bool(th)
                body["chat_template_kwargs"] = kw
            elif self.thinking_param == "deepseek":
                body["thinking"] = {"type": "enabled" if th else "disabled"}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        return body

    # ------------------------------------------------------------------ health
    async def health(self) -> tuple[bool, str]:
        cached = self._health.get()
        if cached:
            return cached
        try:
            key = self._key()
        except LLMError as e:
            return False, str(e)
        try:
            r = await self._client.get(f"{self.base_url}/models", headers=auth_headers(key, self.headers), timeout=8)
        except Exception as e:  # noqa: BLE001
            return False, f"{self.base_url} unreachable: {e}"
        if r.status_code >= 400:
            return self._health.put((False, str(http_error(self.label, r.status_code, r.text))))
        try:
            ids = [m["id"] for m in r.json().get("data", [])]
        except Exception:  # noqa: BLE001
            ids = []
        if not self.remote:
            if self.model in ids or not ids:
                return True, f"{self.base_url} serving {ids}"
            return False, f"model '{self.model}' not in served models {ids}"
        note = "" if not ids or self.model in ids else f" (model '{self.model}' is not in its model list)"
        return self._health.put((True, f"{self.label} reachable, model {self.model}{note}"))

    # ------------------------------------------------------------------ stream
    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        thinking: bool | None = None,
    ) -> AsyncIterator[LLMEvent]:
        pending: dict[int, dict[str, Any]] = {}   # tool call accumulation by index
        finish: str | None = None
        usage: dict[str, Any] = {}
        headers = auth_headers(self._key(), self.headers)
        async with open_stream(self._client, f"{self.base_url}/chat/completions",
                               self._payload(messages, tools, thinking), headers, self.label) as resp:
            async for chunk in iter_sse(resp):
                if chunk.get("error"):
                    raise LLMError(f"{self.label} error: {chunk['error'].get('message', chunk['error'])}")
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta") or {}
                r = delta.get("reasoning_content") or delta.get("reasoning")
                if r and isinstance(r, str):
                    yield LLMEvent("reasoning", text=r)
                if delta.get("content"):
                    yield LLMEvent("content", text=delta["content"])
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", len(pending))
                    slot = pending.setdefault(idx, {"id": None, "name": "", "arguments": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] += fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]

        if self.remote:   # a real answer is the best health check; spares the next /models call
            self._health.put((True, f"{self.label} answered, model {self.model}"))
        for idx in sorted(pending):
            slot = pending[idx]
            slot["id"] = slot["id"] or f"call_{idx}"
            slot["arguments"] = normalize_args(slot["arguments"])
            yield LLMEvent("tool_call", tool_call=slot)
        norm = _FINISH.get(finish or "", finish or "stop")
        if pending and norm == "stop":
            norm = "tool_calls"
        yield LLMEvent("done", finish_reason=norm, usage=_usage(usage))


def _usage(u: dict[str, Any]) -> dict[str, Any]:
    out = {k: u[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens") if k in u}
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or u.get("prompt_cache_hit_tokens")
    if cached:
        out["cached_tokens"] = cached
    return out


# kept for older imports
_normalize_args = normalize_args
