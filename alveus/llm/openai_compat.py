"""OpenAI-compatible chat backend (llama-server, vLLM, Ollama, LM Studio, ...).

Streams /v1/chat/completions over SSE with plain httpx (no SDK), so it works the same with
any server and keeps the dependency surface small.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .base import LLMEvent

log = logging.getLogger(__name__)


class OpenAICompatLLM:
    def __init__(self, profile):
        self.profile = profile
        self.name = profile.get("name", "llm")
        self.model = profile["model"]
        self.base_url = profile["base_url"].rstrip("/")
        self.api_key = profile.get("api_key") or "local"
        self.temperature = profile.get("temperature", 0.7)
        self.top_p = profile.get("top_p", 0.95)
        self.max_tokens = profile.get("max_tokens", 4096)
        self.extra_body: dict[str, Any] = dict(profile.get("extra_body") or {})
        self.reasoning = bool(profile.get("reasoning", False))
        # thinking: True/False forces enable_thinking via chat_template_kwargs; None = model default
        self.thinking = profile.get("thinking", None)
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0),
                                         headers={"Authorization": f"Bearer {self.api_key}"})

    async def health(self) -> tuple[bool, str]:
        try:
            r = await self._client.get(f"{self.base_url}/models", timeout=5)
            r.raise_for_status()
            ids = [m["id"] for m in r.json().get("data", [])]
            if self.model in ids or not ids:
                return True, f"{self.base_url} serving {ids}"
            return False, f"model '{self.model}' not in served models {ids}"
        except Exception as e:  # noqa: BLE001
            return False, f"{self.base_url} unreachable: {e}"

    def _payload(self, messages, tools, thinking) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            # drop private bookkeeping keys such as "_reasoning" (GUI only)
            "messages": [{k: v for k, v in m.items() if not k.startswith("_")} for m in messages],
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            **self.extra_body,
        }
        th = self.thinking if thinking is None else thinking
        if th is not None:
            kw = dict(body.get("chat_template_kwargs") or {})
            kw["enable_thinking"] = bool(th)
            body["chat_template_kwargs"] = kw
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        return body

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

        async with self._client.stream("POST", f"{self.base_url}/chat/completions",
                                       json=self._payload(messages, tools, thinking)) as resp:
            if resp.status_code >= 400:
                text = (await resp.aread()).decode(errors="replace")
                raise RuntimeError(f"LLM HTTP {resp.status_code}: {text[:500]}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    log.debug("bad SSE chunk: %r", data[:200])
                    continue
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta") or {}
                r = delta.get("reasoning_content") or delta.get("reasoning")
                if r:
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

        for idx in sorted(pending):
            slot = pending[idx]
            slot["id"] = slot["id"] or f"call_{idx}"
            slot["arguments"] = _normalize_args(slot["arguments"])
            yield LLMEvent("tool_call", tool_call=slot)
        yield LLMEvent("done", finish_reason=finish, usage=usage)


def _normalize_args(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return "{}"
    try:
        json.loads(s)
        return s
    except json.JSONDecodeError:
        for suffix in ('"}', "}", '"]}', "]}"):  # best-effort repair for truncated JSON
            try:
                json.loads(s + suffix)
                return s + suffix
            except json.JSONDecodeError:
                continue
        log.warning("Unparseable tool arguments: %r", s[:200])
        return json.dumps({"_raw": s})
