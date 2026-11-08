"""The provider-neutral interface every LLM adapter implements.

Conversation format (what the agent keeps in ``Agent.history`` and passes to ``stream``):
OpenAI-style chat messages -- ``system`` / ``user`` / ``assistant`` (optional ``tool_calls``) /
``tool`` (``tool_call_id``) -- plus private keys starting with ``_`` that adapters never send as such:

  _reasoning   the visible reasoning text of that assistant message (GUI only, except for
               providers that need it back, see ``reasoning_replay``)
  _replay      {provider: data} opaque data an adapter returned with the message (``LLMEvent.replay``)
               so it can send the message back exactly as the provider produced it: Anthropic's
               signed thinking blocks, OpenAI's encrypted reasoning items. Other providers ignore
               it and rebuild the message from the neutral fields. ``data["prefix_bound"]`` = the
               data is only valid while every earlier message stays unchanged (the agent drops
               it when it trims old turns).

Each adapter translates this to its own wire format and streams back ``LLMEvent``s.
"""
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass
class LLMEvent:
    """One streamed event from the model.

    kind:
      reasoning  - a chunk of reasoning / thinking summary (shown in the GUI, never spoken)
      content    - a chunk of the user-facing reply
      tool_call  - a complete tool call {id, name, arguments (JSON string)}
      done       - end of this model response: finish_reason, usage and replay filled in

    finish_reason is normalized: stop | tool_calls | length (output limit hit) | refusal
    usage uses prompt_tokens / completion_tokens (+ cached_tokens when the provider reports it)
    """

    kind: Literal["reasoning", "content", "tool_call", "done"]
    text: str = ""
    tool_call: dict[str, Any] | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    replay: dict[str, Any] | None = None


class LLMError(RuntimeError):
    """A failure with a short message fit to be spoken ("DeepSeek rejected the API key")."""


class LLMBackend(Protocol):
    name: str        # profile name
    provider: str    # provider name (key for replay data)
    model: str
    remote: bool     # True when requests leave this machine

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        thinking: bool | None = None,
    ) -> AsyncIterator[LLMEvent]: ...

    async def health(self) -> tuple[bool, str]: ...


def public(m: dict[str, Any]) -> dict[str, Any]:
    """A message without the private ``_`` keys."""
    return {k: v for k, v in m.items() if not k.startswith("_")}


def replay_of(m: dict[str, Any], provider: str) -> Any:
    return (m.get("_replay") or {}).get(provider)


class HealthCache:
    """Remember a health result for ``ttl`` seconds (cloud checks cost a request; local ones do not)."""

    def __init__(self, ttl: float):
        self.ttl = ttl
        self._at = 0.0
        self._val: tuple[bool, str] | None = None

    def get(self) -> tuple[bool, str] | None:
        if self._val is not None and time.monotonic() - self._at < self.ttl:
            return self._val
        return None

    def put(self, val: tuple[bool, str]) -> tuple[bool, str]:
        self._val, self._at = val, time.monotonic()
        return val

    def clear(self) -> None:
        self._val = None
