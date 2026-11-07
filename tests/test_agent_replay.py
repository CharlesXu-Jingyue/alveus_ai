"""Agent loop behaviour that every provider relies on: replay data, trimming, cut-off tool calls."""
import asyncio
import copy

from alveus.agent.loop import Agent
from alveus.config import load_config
from alveus.llm import LLMEvent


class FakeLLM:
    name, provider, model, remote = "fake", "fake", "m", False

    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.sent = []

    async def stream(self, messages, tools=None, *, thinking=None):
        self.sent.append(copy.deepcopy(messages))
        for ev in self.rounds.pop(0):
            yield ev

    async def health(self):
        return True, "ok"


def run(agent, text):
    async def go():
        return [ev async for ev in agent.run(text)]
    return asyncio.run(go())


def call(i="c1"):
    return LLMEvent("tool_call", tool_call={"id": i, "name": "files__rm", "arguments": '{"path": "/tmp/x"}'})


def test_replay_is_stored_with_the_assistant_message():
    llm = FakeLLM([LLMEvent("content", text="hi"), LLMEvent("done", finish_reason="stop", replay={"fake": {"blocks": [1]}})])
    agent = Agent(llm, None, load_config())
    run(agent, "hello")
    assert agent.history[-1] == {"role": "assistant", "content": "hi", "_replay": {"fake": {"blocks": [1]}}}


def test_trimming_drops_prefix_bound_replay_only():
    agent = Agent(FakeLLM([LLMEvent("done", finish_reason="stop")]), None, load_config())
    agent.max_history = 2
    agent.history = [
        {"role": "user", "content": "u1"}, {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2", "_replay": {"anthropic": {"prefix_bound": True}, "openai": {"output": []}}},
        {"role": "user", "content": "u3"},
        {"role": "assistant", "content": "a3", "_replay": {"anthropic": {"prefix_bound": True}}},
    ]
    run(agent, "u4")
    assert [m["content"] for m in agent.history[:4]] == ["u3", "a3", "u4", ""]
    assert "_replay" not in agent.history[1]
    agent.history = [
        {"role": "user", "content": "u1"}, {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2", "_replay": {"anthropic": {"prefix_bound": True}, "openai": {"output": []}}},
    ]
    agent.llm = FakeLLM([LLMEvent("done", finish_reason="stop")])
    run(agent, "u3")
    assert agent.history[1]["content"] == "a2" and agent.history[1]["_replay"] == {"openai": {"output": []}}


def test_cut_off_tool_call_is_not_run_but_answered():
    llm = FakeLLM([call(), LLMEvent("done", finish_reason="length")])
    agent = Agent(llm, None, load_config())
    evs = run(agent, "delete it")
    assert [e.kind for e in evs] == ["done", "error"] and "length limit" in evs[-1].text
    assert agent.history[-2]["tool_calls"][0]["id"] == "c1"
    assert agent.history[-1]["role"] == "tool" and "cut off" in agent.history[-1]["content"]
    assert len(llm.sent) == 1


def test_tool_round_limit_answers_pending_calls():
    llm = FakeLLM([call("c7"), LLMEvent("done", finish_reason="tool_calls", replay={"fake": {"x": 1}})])
    agent = Agent(llm, None, load_config())
    agent.max_rounds = 0
    evs = run(agent, "go")
    assert evs[-1].kind == "error" and "tool-call limit" in evs[-1].text
    assert agent.history[-2]["_replay"] == {"fake": {"x": 1}} and agent.history[-1]["tool_call_id"] == "c7"


def test_refusal_without_text_is_reported():
    agent = Agent(FakeLLM([LLMEvent("done", finish_reason="refusal")]), None, load_config())
    evs = run(agent, "something")
    assert evs[-1].kind == "error" and "declined" in evs[-1].text
