"""OpenAI Responses protocol (``api: openai_responses``), used for OpenAI's own models.

Current OpenAI models only call tools through /responses, not /chat/completions. Requests are
stateless (``store: false`` by default, so OpenAI keeps no copy of the conversation): every turn
sends the whole conversation as ``input`` items. Reasoning items come back with
``encrypted_content``; they are kept in the message's ``_replay`` and sent back verbatim, so the
model keeps its reasoning across tool calls.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from .. import credentials
from .base import HealthCache, LLMError, LLMEvent, replay_of
from .http import auth_headers, http_error, iter_sse, new_client, normalize_args, open_stream

log = logging.getLogger(__name__)


class OpenAIResponsesLLM:
    api = "openai_responses"

    def __init__(self, profile):
        self.profile = profile
        self.name = profile.get("name", "llm")
        self.provider = str(profile.get("provider", "openai"))
        self.label = str(profile.get("label") or self.provider)
        self.model = profile["model"]
        self.base_url = str(profile.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        self.remote = bool(profile.get("remote", True))
        self.temperature = profile.get("temperature")
        self.top_p = profile.get("top_p")
        self.max_tokens = profile.get("max_tokens")
        self.effort = profile.get("effort")
        self.reasoning_summary = profile.get("reasoning_summary", "auto")
        self.store = bool(profile.get("store", False))
        self.extra_body: dict[str, Any] = dict(profile.get("extra_body") or {})
        self.headers: dict[str, Any] = dict(profile.get("headers") or {})
        self._client = new_client()
        self._health = HealthCache(60.0 if self.remote else 0.0)

    def _key(self) -> str | None:
        key = credentials.api_key_for(self.profile)
        if not key and self.remote:
            env = self.profile.get("api_key_env") or "an api_key"
            raise LLMError(f"no API key for {self.label}: set {env} under Settings, API keys")
        return key

    # ------------------------------------------------------------------ conversion
    def _input(self, messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        instructions: list[str] = []
        items: list[dict[str, Any]] = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                instructions.append(str(m.get("content") or ""))
            elif role == "user":
                items.append({"role": "user", "content": m.get("content") or ""})
            elif role == "tool":
                items.append({"type": "function_call_output", "call_id": m.get("tool_call_id", ""),
                              "output": str(m.get("content") or "")})
            elif role == "assistant":
                rep = replay_of(m, self.provider)
                if rep and rep.get("model") == self.model and rep.get("output"):
                    items.extend(rep["output"])
                    continue
                if m.get("content"):
                    items.append({"role": "assistant", "content": m["content"]})
                for tc in m.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    items.append({"type": "function_call", "call_id": tc.get("id", ""),
                                  "name": fn.get("name", ""), "arguments": fn.get("arguments") or "{}"})
        return "\n\n".join(instructions), items

    @staticmethod
    def _tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        out = []
        for t in tools or []:
            fn = t.get("function") or t
            out.append({"type": "function", "name": fn["name"], "description": fn.get("description", ""),
                        "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
                        "strict": False})
        return out

    def _payload(self, messages, tools) -> dict[str, Any]:
        instructions, items = self._input(messages)
        body: dict[str, Any] = {"model": self.model, "input": items, "stream": True, "store": self.store,
                                **self.extra_body}
        if instructions:
            body["instructions"] = instructions
        if self.max_tokens is not None:
            body["max_output_tokens"] = self.max_tokens
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.top_p is not None:
            body["top_p"] = self.top_p
        reasoning = dict(body.get("reasoning") or {})
        if self.effort:
            reasoning["effort"] = self.effort
        if self.reasoning_summary:
            reasoning["summary"] = self.reasoning_summary
        if reasoning:
            body["reasoning"] = reasoning
            # stateless reasoning across tool calls (also the API default for reasoning items now)
            body.setdefault("include", ["reasoning.encrypted_content"])
        if tools:
            body["tools"] = self._tools(tools)
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
            r = await self._client.get(f"{self.base_url}/models/{self.model}",
                                       headers=auth_headers(key, self.headers), timeout=8)
        except Exception as e:  # noqa: BLE001
            return False, f"{self.base_url} unreachable: {e}"
        if r.status_code >= 400:
            return self._health.put((False, str(http_error(self.label, r.status_code, r.text))))
        return self._health.put((True, f"{self.label} reachable, model {self.model}"))

    # ------------------------------------------------------------------ stream
    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        thinking: bool | None = None,   # not switchable here: use effort
    ) -> AsyncIterator[LLMEvent]:
        headers = auth_headers(self._key(), self.headers)
        done_items: list[dict[str, Any]] = []
        final: dict[str, Any] | None = None
        status = "completed"
        last_summary: tuple[Any, Any] | None = None
        async with open_stream(self._client, f"{self.base_url}/responses", self._payload(messages, tools),
                               headers, self.label) as resp:
            async for ev in iter_sse(resp):
                t = ev.get("type", "")
                if t == "response.output_text.delta" or t == "response.refusal.delta":
                    if ev.get("delta"):
                        yield LLMEvent("content", text=ev["delta"])
                elif t.endswith("reasoning_summary_text.delta") or t.endswith("reasoning_text.delta"):
                    key = (ev.get("item_id"), ev.get("summary_index"))
                    if last_summary is not None and key != last_summary:
                        yield LLMEvent("reasoning", text="\n\n")
                    last_summary = key
                    if ev.get("delta"):
                        yield LLMEvent("reasoning", text=ev["delta"])
                elif t == "response.output_item.done" and isinstance(ev.get("item"), dict):
                    done_items.append(ev["item"])
                elif t in ("response.completed", "response.incomplete"):
                    final = ev.get("response") or {}
                    status = final.get("status") or t.rsplit(".", 1)[-1]
                elif t == "response.failed":
                    err = ((ev.get("response") or {}).get("error") or {})
                    raise LLMError(f"{self.label} failed: {err.get('message') or err or 'unknown error'}")
                elif t == "error":
                    raise LLMError(f"{self.label} error: {ev.get('message') or ev.get('code') or ev}")

        output = (final or {}).get("output") or done_items
        calls = [it for it in output if it.get("type") == "function_call"]
        for it in calls:
            yield LLMEvent("tool_call", tool_call={"id": it.get("call_id") or it.get("id"), "name": it.get("name", ""),
                                                   "arguments": normalize_args(it.get("arguments") or "")})
        reason = ((final or {}).get("incomplete_details") or {}).get("reason")
        if calls:
            finish = "tool_calls" if status == "completed" else "length"
        elif status == "incomplete":
            finish = "refusal" if reason == "content_filter" else "length"
        else:
            finish = "stop"
        u = (final or {}).get("usage") or {}
        usage = {"prompt_tokens": u.get("input_tokens"), "completion_tokens": u.get("output_tokens")}
        cached = (u.get("input_tokens_details") or {}).get("cached_tokens")
        if cached:
            usage["cached_tokens"] = cached
        replay = {self.provider: {"model": self.model, "output": [_input_item(it) for it in output]}}
        self._health.put((True, f"{self.label} answered, model {self.model}"))
        yield LLMEvent("done", finish_reason=finish, usage={k: v for k, v in usage.items() if v is not None},
                       replay=replay)


def _input_item(item: dict[str, Any]) -> dict[str, Any]:
    """An output item as it can be sent back in ``input``: reasoning items keep their id and
    encrypted content; messages and calls drop the server-side id and status (optional on input,
    and not resolvable when nothing is stored)."""
    if item.get("type") == "reasoning":
        return {k: v for k, v in item.items() if k != "status"}
    return {k: v for k, v in item.items() if k not in ("id", "status")}
