"""Qwen3-TTS engine: the worker protocol (with a fake worker), the cloning mode per sentence,
transcripts, gender, and the voices API."""
import json
import os
import sys
import textwrap

import numpy as np
import pytest
import soundfile as sf

from alveus.agent.loop import voice_is_female
from alveus.config import DotDict, load_config
from alveus.tts.qwen3_tts import Qwen3TTS, token_budget, transcript_for

FAKE = textwrap.dedent('''
    import json, os, sys
    import numpy as np
    out = os.fdopen(os.dup(1), "wb", buffering=0); os.dup2(2, 1)
    log = open(sys.argv[1] + ".requests", "a")
    if os.environ.get("FAKE_FAIL"):
        out.write(b'{"ready": false, "error": "CUDA out of memory"}\\n'); sys.exit(0)
    out.write(json.dumps({"ready": True, "seconds": 0.1, "vram_gb": 0}).encode() + b"\\n")
    for line in sys.stdin:
        req = json.loads(line); log.write(line); log.flush()
        if req["text"] == "die":
            sys.exit(1)
        a = np.full(2400, 0.1, dtype=np.float32)
        out.write(json.dumps({"ok": True, "sr": 24000, "n": a.size, "seconds": 0.01}).encode() + b"\\n" + a.tobytes())
''')


@pytest.fixture
def voices(tmp_path):
    d = tmp_path / "voices"
    d.mkdir()
    for name, words in (("f_aki_ja", "今日はいい天気ですね。"), ("m_bob", None)):
        sf.write(d / f"{name}.wav", np.zeros(24000, dtype=np.float32), 24000)
        if words:
            (d / f"{name}.txt").write_text(words + "\n", encoding="utf-8")
    return d


def engine(tmp_path, voices, **opts):
    fake = tmp_path / "fake_worker.py"
    fake.write_text(FAKE)
    e = Qwen3TTS({"python": sys.executable, "voice_ref": "f_aki_ja.wav", **opts}, "cpu", voices_dir=str(voices))
    e.worker = fake
    e.model_source = lambda: str(tmp_path / "weights")          # the fake logs requests next to this path
    return e


def requests(tmp_path):
    return [json.loads(x) for x in (tmp_path / "weights.requests").read_text().splitlines()]


def test_transcripts_and_budget(voices):
    assert transcript_for(str(voices / "f_aki_ja.wav")) == "今日はいい天気ですね。"
    assert transcript_for(str(voices / "m_bob.wav")) is None
    assert token_budget("Hi.") == 96 and token_budget("x" * 5000) == 2048
    assert token_budget("今日はもう遅いから、続きは明日にしよう。") > token_budget("It is late.")


def test_words_go_along_only_in_the_recordings_language(tmp_path, voices):
    e = engine(tmp_path, voices)
    assert e.ref_lang == "ja"
    ja, en = e.request("明日は雨が降るかもしれません。"), e.request("It may rain tomorrow, so take an umbrella.")
    assert ja["language"] == "japanese" and ja["ref_text"] == "今日はいい天気ですね。"
    assert en["language"] == "english" and en["ref_text"] is None
    e.reconfigure({"python": sys.executable, "voice_ref": "m_bob.wav", "language": "en"}, str(voices))
    assert e.request("Hello there.")["ref_text"] is None and e.voice_ref.endswith("m_bob.wav")


def test_worker_round_trip_restart_and_close(tmp_path, voices):
    e = engine(tmp_path, voices)
    a = e.synthesize("Hello there. 明日は雨が降るかもしれません。")      # two languages: two requests
    assert a.dtype == np.float32 and a.size >= 4800 and e.sample_rate == 24000
    sent = requests(tmp_path)
    assert [r["language"] for r in sent] == ["english", "japanese"] and sent[1]["ref_text"]
    pid = e._model.pid
    e.synthesize("die")                                          # the worker dies: logged, no exception
    assert e.synthesize("Back again.").size == 2400 and e._model.pid != pid   # started again
    proc = e._model
    e.close()
    assert proc.poll() is not None and e._model is None


def test_a_worker_that_cannot_start_says_why(tmp_path, voices, monkeypatch):
    monkeypatch.setenv("FAKE_FAIL", "1")
    with pytest.raises(RuntimeError, match="CUDA out of memory"):
        engine(tmp_path, voices).load()
    e = Qwen3TTS({"python": "/nonexistent/python"}, "cpu", voices_dir=str(voices))
    with pytest.raises(RuntimeError, match="install_qwen3_tts.sh"):
        e.load()


def test_no_voice_chosen_uses_the_first_recording_or_warns(tmp_path, voices):
    e = Qwen3TTS({"python": sys.executable}, "cpu", voices_dir=str(voices))
    assert e.voice_ref.endswith("f_aki_ja.wav") and e.warning is None
    e = Qwen3TTS({"python": sys.executable, "voice_ref": "gone.wav"}, "cpu", voices_dir=str(voices))
    assert "not found" in e.warning and e.voice_ref.endswith("f_aki_ja.wav")
    e = Qwen3TTS({"python": sys.executable}, "cpu", voices_dir=str(tmp_path / "empty"))
    assert e.voice_ref is None and "put a WAV" in e.warning


def test_reconfigure_reloads_only_for_another_model(tmp_path, voices):
    e = engine(tmp_path, voices)
    assert e.reconfigure({"python": sys.executable, "voice_ref": "m_bob.wav", "temperature": 0.7}, str(voices))
    assert e.temperature == 0.7
    assert not e.reconfigure({"python": sys.executable, "model": "0_6b"}, str(voices))


def test_gender_follows_the_recording_name():
    cfg = load_config()
    cfg["tts"] = {**cfg["tts"], "backend": "qwen3", "voice_gender": "auto", "qwen3": {"model": "1_7b", "voice_ref": "f_aki_ja.wav"}}
    assert voice_is_female(DotDict(cfg))
    cfg["tts"]["qwen3"] = {"model": "1_7b", "voice_ref": "x.wav", "models": {"1_7b": {"voice_ref": "m_bob.wav"}}}
    assert not voice_is_female(DotDict(cfg))


def test_voices_api_lists_words_and_writes_them_down(tmp_path, voices):
    from fastapi.testclient import TestClient

    from alveus.api import build_app

    class STT:
        def transcribe(self, audio, sr):
            assert sr == 16000 and audio.ndim == 1
            return "hello, this is Bob"
    a = type("A", (), {})()
    a.cfg, a.agent, a.stt, a.tts = load_config(), None, STT(), None
    c = TestClient(build_app(a))
    r = c.get("/voices", params={"dir": str(voices)}).json()
    assert r["files"] == ["f_aki_ja.wav", "m_bob.wav"] and r["texts"] == ["f_aki_ja.wav"]
    r = c.post("/voices/transcribe", json={"name": "m_bob.wav", "dir": str(voices)}).json()
    assert r["text"] == "hello, this is Bob" and (voices / "m_bob.txt").read_text().strip() == r["text"]
    assert c.post("/voices/transcribe", json={"name": "../x.wav", "dir": str(voices)}).status_code == 404
    assert os.path.exists(voices / "m_bob.txt")


def test_no_voice_chosen_gender_follows_the_first_recording(voices):
    cfg = load_config()
    cfg["tts"] = {**cfg["tts"], "backend": "qwen3", "voice_gender": "auto", "voices_dir": str(voices), "qwen3": {"model": "1_7b"}}
    assert voice_is_female(DotDict(cfg))                     # f_aki_ja.wav comes first
