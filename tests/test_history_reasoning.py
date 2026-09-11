"""Reasoning is kept with each assistant turn for the GUI, and never sent back to the LLM."""
from alveus.api import _normalize_history
from alveus.llm.openai_compat import OpenAICompatLLM


def test_normalize_history_exposes_reasoning():
    hist = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "_reasoning": "need a tool",
         "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        {"role": "assistant", "content": "done", "_reasoning": "tool said ok"},
        {"role": "assistant", "content": "plain"},
    ]
    out = _normalize_history(hist)
    assert [t["role"] for t in out] == ["user", "assistant", "assistant"]
    assert out[1]["reasoning"] == "need a tool\n\ntool said ok"
    assert out[1]["text"] == "done" and out[1]["tools"][0]["result"] == "ok"
    assert "reasoning" not in out[2]


def test_payload_strips_private_keys():
    llm = OpenAICompatLLM.__new__(OpenAICompatLLM)
    llm.model, llm.temperature, llm.top_p, llm.max_tokens, llm.extra_body, llm.thinking = "m", 0.5, 1.0, 10, {}, None
    body = llm._payload([{"role": "assistant", "content": "x", "_reasoning": "secret"}], None, None)
    assert body["messages"] == [{"role": "assistant", "content": "x"}]
