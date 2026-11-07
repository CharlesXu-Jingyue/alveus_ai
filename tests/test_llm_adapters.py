"""The three protocol adapters against recorded-style streams (no network)."""
import asyncio
import json

import httpx
import pytest

from alveus.llm import LLMError, make_llm
from alveus.llm.providers import resolve

LLM = {"temperature": 0.7, "top_p": 0.95, "max_tokens": 4096, "effort": None, "max_tool_rounds": 12}
TOOLS = [{"type": "function", "function": {"name": "web__weather", "description": "Weather for a city",
                                           "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}}]
CONVO = [
    {"role": "system", "content": "You are Alveus."},
    {"role": "user", "content": "Weather in Boston?"},
    {"role": "assistant", "content": None, "_reasoning": "need the tool",
     "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "web__weather", "arguments": '{"city": "Boston"}'}}]},
    {"role": "tool", "tool_call_id": "call_1", "content": '{"temp_c": 12}'},
    {"role": "assistant", "content": "It is 12 degrees.", "_reasoning": "answer"},
    {"role": "user", "content": "And tomorrow?"},
]


def collect(agen):
    async def run():
        return [ev async for ev in agen]
    return asyncio.run(run())


def sse(*objs, events=False):
    out = []
    for o in objs:
        if events:
            out.append(f"event: {o['type']}")
        out.append("data: " + json.dumps(o))
        out.append("")
    return ("\n".join(out) + "\n").encode()


def profile(raw, name="t"):
    return resolve(name, raw, LLM)


# ------------------------------------------------------------------ openai_chat
def test_chat_payload_local_server():
    llm = make_llm(profile({"provider": "llama_server", "model": "bonsai", "thinking": False, "extra_body": {"top_k": 20}}))
    body = llm._payload(CONVO, TOOLS, None)
    assert body["temperature"] == 0.7 and body["max_tokens"] == 4096 and body["top_k"] == 20
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert all("reasoning_content" not in m and "_reasoning" not in m for m in body["messages"])
    assert "reasoning_effort" not in body


def test_chat_payload_deepseek_sends_reasoning_back_and_thinking_switch(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-x")
    llm = make_llm(profile({"provider": "deepseek", "model": "deepseek-v4-pro", "thinking": True, "effort": "high"}))
    body = llm._payload(CONVO, TOOLS, None)
    assistants = [m for m in body["messages"] if m["role"] == "assistant"]
    assert [m["reasoning_content"] for m in assistants] == ["need the tool", "answer"]
    assert body["thinking"] == {"type": "enabled"} and body["reasoning_effort"] == "high"
    assert "chat_template_kwargs" not in body


def test_chat_missing_key_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setenv("ALVEUS_SECRETS", str(tmp_path / "none.env"))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    llm = make_llm(profile({"provider": "deepseek", "model": "deepseek-v4-pro"}))
    with pytest.raises(LLMError, match="DEEPSEEK_API_KEY"):
        collect(llm.stream(CONVO))
    ok, msg = asyncio.run(llm.health())
    assert not ok and "DEEPSEEK_API_KEY" in msg


def test_chat_stream_parses_reasoning_content_and_tool_calls(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-x")
    seen = {}

    def handler(req: httpx.Request):
        seen["auth"] = req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        chunks = [
            {"choices": [{"delta": {"reasoning_content": "think "}}]},
            {"choices": [{"delta": {"content": "Let me look."}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_9", "function": {"name": "web__weather", "arguments": '{"ci'}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'ty": "Boston"}'}}]}, "finish_reason": "tool_calls"}]},
            {"choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 9, "prompt_cache_hit_tokens": 32}},
        ]
        return httpx.Response(200, content=sse(*chunks) + b"data: [DONE]\n\n", headers={"content-type": "text/event-stream"})

    llm = make_llm(profile({"provider": "deepseek", "model": "deepseek-v4-pro"}))
    llm._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    evs = collect(llm.stream(CONVO, TOOLS))
    assert seen["auth"] == "Bearer sk-x" and seen["body"]["model"] == "deepseek-v4-pro"
    assert [e.kind for e in evs] == ["reasoning", "content", "tool_call", "done"]
    assert evs[2].tool_call == {"id": "call_9", "name": "web__weather", "arguments": '{"city": "Boston"}'}
    assert evs[3].finish_reason == "tool_calls" and evs[3].usage["cached_tokens"] == 32


def test_chat_http_error_is_short_and_readable(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-bad")
    handler = lambda req: httpx.Response(401, json={"error": {"message": "Authentication Fails"}})  # noqa: E731
    llm = make_llm(profile({"provider": "deepseek", "model": "deepseek-v4-pro"}))
    llm._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError, match="DeepSeek rejected the API key: Authentication Fails"):
        collect(llm.stream(CONVO))


# ------------------------------------------------------------------ openai_responses
RESP_OUTPUT = [
    {"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": "Weather lookup"}],
     "encrypted_content": "ENC", "status": "completed"},
    {"type": "message", "id": "msg_1", "status": "completed", "role": "assistant",
     "content": [{"type": "output_text", "text": "Let me check.", "annotations": []}]},
    {"type": "function_call", "id": "fc_1", "call_id": "call_7", "name": "web__weather",
     "arguments": '{"city":"Boston"}', "status": "completed"},
]


def test_responses_payload_is_stateless_and_rebuilds_foreign_history(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-o")
    llm = make_llm(profile({"provider": "openai", "model": "gpt-6.1-sol", "effort": "low"}))
    body = llm._payload(CONVO, TOOLS)
    assert body["store"] is False and body["instructions"] == "You are Alveus."
    assert "temperature" not in body and "top_p" not in body and body["max_output_tokens"] == 4096
    assert body["reasoning"] == {"effort": "low", "summary": "auto"}
    assert body["tools"][0] == {"type": "function", "name": "web__weather", "description": "Weather for a city",
                                "parameters": TOOLS[0]["function"]["parameters"], "strict": False}
    kinds = [i.get("type") or i.get("role") for i in body["input"]]
    assert kinds == ["user", "function_call", "function_call_output", "assistant", "user"]
    assert body["input"][2] == {"type": "function_call_output", "call_id": "call_1", "output": '{"temp_c": 12}'}


def test_responses_stream_and_replay(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-o")

    def handler(req: httpx.Request):
        evs = [
            {"type": "response.created", "response": {"status": "in_progress"}},
            {"type": "response.reasoning_summary_text.delta", "item_id": "rs_1", "summary_index": 0, "delta": "Weather "},
            {"type": "response.reasoning_summary_text.delta", "item_id": "rs_1", "summary_index": 0, "delta": "lookup"},
            {"type": "response.output_item.done", "item": RESP_OUTPUT[0]},
            {"type": "response.output_text.delta", "item_id": "msg_1", "delta": "Let me check."},
            {"type": "response.output_item.done", "item": RESP_OUTPUT[1]},
            {"type": "response.function_call_arguments.delta", "delta": '{"city"'},
            {"type": "response.output_item.done", "item": RESP_OUTPUT[2]},
            {"type": "response.completed", "response": {"status": "completed", "output": RESP_OUTPUT,
                                                         "usage": {"input_tokens": 90, "output_tokens": 20,
                                                                   "input_tokens_details": {"cached_tokens": 64}}}},
        ]
        return httpx.Response(200, content=sse(*evs, events=True), headers={"content-type": "text/event-stream"})

    llm = make_llm(profile({"provider": "openai", "model": "gpt-6.1-sol"}))
    llm._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    evs = collect(llm.stream(CONVO, TOOLS))
    assert "".join(e.text for e in evs if e.kind == "reasoning") == "Weather lookup"
    assert "".join(e.text for e in evs if e.kind == "content") == "Let me check."
    call = next(e.tool_call for e in evs if e.kind == "tool_call")
    assert call == {"id": "call_7", "name": "web__weather", "arguments": '{"city":"Boston"}'}
    done = evs[-1]
    assert done.finish_reason == "tool_calls" and done.usage == {"prompt_tokens": 90, "completion_tokens": 20, "cached_tokens": 64}
    out = done.replay["openai"]["output"]
    assert out[0]["id"] == "rs_1" and out[0]["encrypted_content"] == "ENC"     # reasoning kept whole
    assert "id" not in out[1] and "id" not in out[2] and "status" not in out[2]
    # sent back verbatim on the next request, with the same model only
    msg = {"role": "assistant", "content": "Let me check.", "_replay": done.replay,
           "tool_calls": [{"id": "call_7", "type": "function", "function": {"name": "web__weather", "arguments": "{}"}}]}
    _, items = llm._input([{"role": "user", "content": "q"}, msg])
    assert items[1:] == out
    llm.model = "another-model"
    _, items = llm._input([{"role": "user", "content": "q"}, msg])
    assert [i.get("type") or i.get("role") for i in items] == ["user", "assistant", "function_call"]


# ------------------------------------------------------------------ anthropic_messages
def claude(**kw):
    return make_llm(profile({"provider": "anthropic", "model": "claude-opus-5-5", "api_key": "sk-ant-test",
                             "max_tokens": 16000, **kw}))


def test_anthropic_conversion():
    llm = claude()
    convo = CONVO[:4] + [{"role": "tool", "tool_call_id": "call_2", "content": "second"},
                         {"role": "assistant", "content": ""}] + CONVO[4:]
    system, msgs = llm.convert(convo)
    assert system == "You are Alveus."
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant", "user"]
    assert msgs[1]["content"] == [{"type": "tool_use", "id": "call_1", "name": "web__weather", "input": {"city": "Boston"}}]
    # consecutive tool results become one user message; the empty assistant reply is skipped
    assert [b["tool_use_id"] for b in msgs[2]["content"]] == ["call_1", "call_2"]
    assert llm.convert_tools(TOOLS)[0] == {"name": "web__weather", "description": "Weather for a city",
                                           "input_schema": TOOLS[0]["function"]["parameters"]}
    p = llm.params(CONVO, TOOLS, None)
    assert p["thinking"] == {"type": "adaptive", "display": "summarized"} and p["cache_control"] == {"type": "ephemeral"}
    assert "temperature" not in p and "top_p" not in p and "output_config" not in p
    assert claude(effort="low").params(CONVO, None, None)["output_config"] == {"effort": "low"}
    assert "thinking" not in claude(thinking=False).params(CONVO, None, None)


def test_anthropic_replays_its_own_blocks_verbatim():
    blocks = [{"type": "thinking", "thinking": "plan", "signature": "SIG"},
              {"type": "tool_use", "id": "toolu_1", "name": "web__weather", "input": {"city": "Boston"}}]
    msg = {"role": "assistant", "content": None, "_replay": {"anthropic": {"content": blocks, "prefix_bound": True}},
           "tool_calls": [{"id": "toolu_1", "type": "function", "function": {"name": "web__weather", "arguments": "{}"}}]}
    _, msgs = claude().convert([{"role": "user", "content": "q"}, msg])
    assert msgs[1] == {"role": "assistant", "content": blocks}


CLAUDE_STREAM = [
    {"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                                          "content": [], "stop_reason": None, "stop_sequence": None,
                                          "usage": {"input_tokens": 10, "output_tokens": 1, "cache_read_input_tokens": 500,
                                                    "cache_creation_input_tokens": 0}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "Need the weather."}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "SIG123"}},
    {"type": "content_block_stop", "index": 0},
    {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Checking."}},
    {"type": "content_block_stop", "index": 1},
    {"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "web__weather", "input": {}}},
    {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": '{"city": "Bos'}},
    {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": 'ton"}'}},
    {"type": "content_block_stop", "index": 2},
    {"type": "message_delta", "delta": {"type": "message_delta", "stop_reason": "tool_use", "stop_sequence": None},
     "usage": {"output_tokens": 42}},
    {"type": "message_stop"},
]


def _mock_claude(llm, handler):
    import anthropic
    import httpx2
    llm._client = anthropic.AsyncAnthropic(api_key="sk-ant-test", max_retries=0, http_client=anthropic.DefaultAsyncHttpxClient(
        transport=httpx2.MockTransport(handler)))
    llm._client_key = "sk-ant-test"


def test_anthropic_stream_with_tool_use_and_signature():
    seen = []

    def handler(req):
        seen.append({"body": json.loads(req.content), "beta": req.headers.get("anthropic-beta", "")})
        import httpx2
        return httpx2.Response(200, content=sse(*CLAUDE_STREAM, events=True), headers={"content-type": "text/event-stream"})

    llm = claude()
    _mock_claude(llm, handler)
    evs = collect(llm.stream(CONVO, TOOLS))
    body = seen[0]["body"]
    assert body["fallbacks"] == "default" and "server-side-fallback" in seen[0]["beta"]
    assert body["system"] == "You are Alveus." and body["tools"][0]["name"] == "web__weather"
    assert "temperature" not in body
    assert [e.kind for e in evs] == ["reasoning", "content", "tool_call", "done"]
    assert json.loads(evs[2].tool_call["arguments"]) == {"city": "Boston"} and evs[2].tool_call["id"] == "toolu_1"
    done = evs[3]
    assert done.finish_reason == "tool_calls"
    assert done.usage == {"prompt_tokens": 510, "completion_tokens": 42, "cached_tokens": 500}
    rep = done.replay["anthropic"]
    assert rep["prefix_bound"] is True
    assert rep["content"][0] == {"type": "thinking", "thinking": "Need the weather.", "signature": "SIG123"}
    assert rep["content"][2]["type"] == "tool_use" and rep["content"][2]["input"] == {"city": "Boston"}


def test_anthropic_retries_without_fallbacks_when_the_model_lacks_them():
    calls = []

    def handler(req):
        import httpx2
        body = json.loads(req.content)
        calls.append("fallbacks" in body)
        if "fallbacks" in body:
            return httpx2.Response(400, json={"type": "error", "error": {"type": "invalid_request_error",
                                                                          "message": "fallbacks: not supported for this model"}})
        return httpx2.Response(200, content=sse(*CLAUDE_STREAM, events=True), headers={"content-type": "text/event-stream"})

    llm = claude(model="claude-haiku-5-5")
    _mock_claude(llm, handler)
    evs = collect(llm.stream(CONVO, TOOLS))
    assert calls == [True, False] and evs[-1].kind == "done" and llm.fallbacks is None


def test_anthropic_auth_error_is_readable():
    def handler(req):
        import httpx2
        return httpx2.Response(401, json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})

    llm = claude(fallbacks=None)
    _mock_claude(llm, handler)
    with pytest.raises(LLMError, match="rejected the API key"):
        collect(llm.stream(CONVO))


def test_anthropic_stream_closes_cleanly_when_interrupted():
    import httpx2
    closed = []

    class Body(httpx2.AsyncByteStream):
        """A streaming body that records whether the SDK closed it."""
        def __init__(self):
            self.data = sse(*CLAUDE_STREAM, events=True)

        async def __aiter__(self):
            for i in range(0, len(self.data), 64):
                yield self.data[i:i + 64]
                await asyncio.sleep(0)

        async def aclose(self):
            closed.append(True)

    def handler(req):
        import httpx2
        return httpx2.Response(200, stream=Body(), headers={"content-type": "text/event-stream"})

    llm = claude()
    _mock_claude(llm, handler)

    async def go():
        gen = llm.stream(CONVO, TOOLS)
        first = await gen.__anext__()
        await gen.aclose()          # what Agent.run does on interrupt
        return first

    assert asyncio.run(go()).kind == "reasoning"
    assert closed, "the HTTP response was not closed"
