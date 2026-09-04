from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass
class LLMEvent:
    """One streamed event from the model.

    kind:
      reasoning  - a chunk of hidden chain-of-thought (never spoken)
      content    - a chunk of the user-facing reply
      tool_call  - a complete tool call {id, name, arguments(str)}
      done       - end of turn; finish_reason and usage filled in
    """

    kind: Literal["reasoning", "content", "tool_call", "done"]
    text: str = ""
    tool_call: dict[str, Any] | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


class LLMBackend(Protocol):
    name: str

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        thinking: bool | None = None,
    ) -> AsyncIterator[LLMEvent]: ...

    async def health(self) -> tuple[bool, str]: ...
