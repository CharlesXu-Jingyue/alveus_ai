"""Confirmation questions (answers, silence, trusted tools) and applying settings without a restart."""
import asyncio
import json

import numpy as np

from alveus import live, voice
from alveus.agent.loop import Agent, describe_action
from alveus.agent.mcp_client import ToolInfo
from alveus.config import DotDict, load_config
from alveus.llm import LLMEvent
from alveus.voice import VoiceAssistant, classify_answer


def test_classify_answer():
    for t in ("Yes.", "yeah, go ahead", "Okay", "sure thing", "Go ahead please", "Yes, close it."):
        assert classify_answer(t) == "yes", t
    for t in ("No.", "no, wait", "Don't.", "cancel that", "Wait"):
        assert classify_answer(t) == "no", t
    for t in ("", "hmm what?", "Firefox", "I think so maybe"):
        assert classify_answer(t) is None, t


def test_describe_action_in_plain_words():
    assert describe_action("close_window", {"title_substring": "Firefox"}) == "close window: Firefox"
    assert describe_action("delete_path", {"path": "/tmp/x", "recursive": True}) == "delete path: /tmp/x"
    assert len(describe_action("run_command", {"command": "x" * 500})) == 160


# ------------------------------------------------------------------ the agent's confirmation gate
class Hub:
    def __init__(self, *tools):
        self.tools = {t.full_name: t for t in tools}
        self.calls = []

    def get(self, name):
        return self.tools.get(name)

    def openai_tools(self):
        return [t.as_openai() for t in self.tools.values()]

    async def call(self, name, args):
        self.calls.append((name, args))
        return json.dumps({"ok": True})


class OneCall:
    """A model that calls one tool, then answers."""
    name, provider, model, remote = "fake", "fake", "m", False

    def __init__(self, tool, args):
        self.rounds = [[LLMEvent("tool_call", tool_call={"id": "c1", "name": tool, "arguments": json.dumps(args)}),
                        LLMEvent("done", finish_reason="tool_calls")],
                       [LLMEvent("content", text="ok"), LLMEvent("done", finish_reason="stop")]]

    async def stream(self, messages, tools=None, *, thinking=None):
        for ev in self.rounds.pop(0):
            yield ev


def run_turn(agent, confirm):
    async def go():
        return [ev async for ev in agent.run("close it", confirm=confirm)]
    asyncio.run(go())
    return [m for m in agent.history if m["role"] == "tool"][-1]["content"]


CLOSE = ToolInfo(server="desktop", name="close_window", full_name="desktop__close_window", description="", schema={},
                 destructive=True)
SHELL = ToolInfo(server="files", name="run_command", full_name="files__run_command", description="", schema={})


def test_silence_is_no_answer_not_a_refusal():
    asked = []

    async def confirm(desc):
        asked.append(desc)
        return {"ok": False, "reason": "no_answer"}
    hub = Hub(CLOSE)
    agent = Agent(OneCall("desktop__close_window", {"title_substring": "Firefox"}), hub, load_config())
    out = run_turn(agent, confirm)
    assert asked == ["close window: Firefox"] and hub.calls == []
    assert "No clear answer" in out and "declined" not in out and not agent._declined_this_turn


def test_a_real_no_still_blocks_retries():
    async def confirm(desc):
        return False
    agent = Agent(OneCall("desktop__close_window", {"title_substring": "Firefox"}), Hub(CLOSE), load_config())
    assert "declined" in run_turn(agent, confirm) and agent._declined_this_turn


def test_trusted_tools_skip_the_question_but_shell_never_does():
    cfg = load_config()
    cfg["tools"]["no_confirm"] = ["desktop__close_window", "files__run_command"]
    asked = []

    async def confirm(desc):
        asked.append(desc)
        return True
    hub = Hub(CLOSE)
    run_turn(Agent(OneCall("desktop__close_window", {"title_substring": "Firefox"}), hub, DotDict(cfg)), confirm)
    assert asked == [] and hub.calls[0][0] == "desktop__close_window"
    hub = Hub(SHELL)
    run_turn(Agent(OneCall("files__run_command", {"command": "rm -rf /tmp/x"}), hub, DotDict(cfg)), confirm)
    assert asked == ["run command: rm -rf /tmp/x"]


# ------------------------------------------------------------------ patient recording of an answer
class Clock:
    t = 1000.0

    def time(self):
        return self.t


class Mic:
    """Frames of 32 ms; each read advances the fake clock by one frame."""
    def __init__(self, pattern, clock):
        self.frames = [np.full(512, 1.0 if s else 0.0, dtype=np.float32) for s in pattern]
        self.clock = clock

    def drain(self):
        pass

    def read(self, timeout):
        self.clock.t += 0.032
        return self.frames.pop(0) if self.frames else np.zeros(512, dtype=np.float32)


class VAD:
    def reset(self):
        pass

    def is_speech(self, f):
        return bool(f[0])


class Trigger:
    def take(self):
        return False


def record(pattern, patient, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(voice, "time", clock)
    fake = type("V", (), {})()
    fake.cfg, fake.vad, fake.audio_in, fake.wake, fake.trigger = load_config(), VAD(), Mic(pattern, clock), None, Trigger()
    return VoiceAssistant._record_utterance(fake, None, 10.0, False, patient)


def test_a_blip_does_not_end_the_wait_for_an_answer(monkeypatch):
    blip_then_yes = [1, 1] + [0] * 40 + [1] * 15 + [0] * 40      # 64 ms click, 1.3 s quiet, 0.5 s "yes"
    assert record(blip_then_yes, patient=False, monkeypatch=monkeypatch) is None   # the old behaviour
    rec = record(blip_then_yes, patient=True, monkeypatch=monkeypatch)
    assert rec is not None and int((rec > 0).sum() / 512) == 15                     # just the answer


# ------------------------------------------------------------------ live settings
class FakeTTS:
    name = "kokoro"

    def __init__(self):
        self.applied = None
        self._pipe = object()

    def reconfigure(self, opts):
        self.applied = opts
        return True


def assistant(cfg):
    a = type("A", (), {})()
    a.cfg, a.tts, a.stt, a.load_speech = cfg, FakeTTS(), FakeTTS(), True
    a.agent = Agent(OneCall("x", {}), None, cfg)
    return a


def test_diff_paths():
    assert live.diff_paths({"a": {"b": 1, "c": 2}, "_env": 1}, {"a": {"b": 1, "c": 3}, "d": 4, "_env": 2}) == ["a.c", "d"]


def test_live_apply_voice_names_model_and_restart_report(monkeypatch):
    monkeypatch.delenv("ALVEUS_LLM_PROFILE", raising=False)
    monkeypatch.setattr("alveus.llm.service.reconcile_local_server", lambda cfg, prof: None)
    old = load_config()
    a = assistant(old)
    new = DotDict(json.loads(json.dumps(old, default=str)))
    new["tts"]["backend"] = old.tts.backend
    new["tts"][old.tts.backend] = {**(old.tts.get(old.tts.backend) or {}), "voice": "bf_emma", "speed": 1.1}
    new["assistant"]["user_name"] = "Dr. X"
    new["llm"]["profile"] = "deepseek"
    new["audio"]["input_device"] = "some-mic"
    llm_before, prompt_before = a.agent.llm, a.agent.system_prompt
    rep = asyncio.run(live.apply_config(a, new))
    assert a.tts.applied["voice"] == "bf_emma" and a.tts.applied["speed"] == 1.1           # in place, no reload
    assert a.agent.llm is not llm_before and a.agent.llm.model == "deepseek-v4-pro"        # model switched
    assert "Dr. X" in a.agent.system_prompt and a.agent.system_prompt != prompt_before
    assert rep["restart"] == ["microphone"] and not rep["errors"] and a.cfg is new


def test_live_apply_reloads_another_engine(monkeypatch):
    old = load_config()
    a = assistant(old)
    loaded = []

    class Other:
        name = "chatterbox"

        def load(self):
            loaded.append(True)
    monkeypatch.setattr("alveus.tts.make_tts", lambda cfg: Other())
    new = DotDict(json.loads(json.dumps(old, default=str)))
    new["tts"]["backend"] = "chatterbox" if old.tts.backend != "chatterbox" else "kokoro"
    rep = asyncio.run(live.apply_config(a, new))
    assert isinstance(a.tts, Other) and loaded == [True] and rep["reloaded"]
