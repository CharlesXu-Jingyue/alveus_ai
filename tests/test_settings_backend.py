"""Per-model engine settings, local model discovery and the settings page's API helpers."""
import asyncio

from alveus.agent.loop import voice_is_female
from alveus.config import DotDict, engine_opts, load_config
from alveus.llm import catalog
from alveus.llm.service import context_of, server_args


def cfg_with(tts=None, stt=None):
    cfg = load_config()
    if tts:
        cfg["tts"] = {**cfg["tts"], **tts}
    if stt:
        cfg["stt"] = {**cfg["stt"], **stt}
    return DotDict(cfg)


def test_model_block_overrides_engine_block():
    cfg = cfg_with(tts={"backend": "chatterbox", "voices_dir": "/v",
                        "chatterbox": {"model": "multilingual", "voice_ref": "m_engine.wav", "exaggeration": 0.5,
                                       "models": {"multilingual": {"voice_ref": "f_mei.wav", "language": "zh"},
                                                  "turbo": {"voice_ref": None}}}})
    o = engine_opts(cfg, "tts")
    assert o["voice_ref"] == "f_mei.wav" and o["language"] == "zh" and o["exaggeration"] == 0.5
    assert o["voices_dir"] == "/v" and "models" not in o          # section fallback, no nested blocks
    cfg["tts"]["chatterbox"]["model"] = "turbo"
    assert engine_opts(cfg, "tts")["voice_ref"] is None            # explicit null = built-in voice
    cfg["tts"]["chatterbox"]["model"] = "standard"
    assert engine_opts(cfg, "tts")["voice_ref"] == "m_engine.wav"  # no block: engine value


def test_voice_gender_follows_the_selected_model():
    cfg = cfg_with(tts={"backend": "chatterbox", "voice_gender": "auto",
                        "chatterbox": {"model": "multilingual", "voice_ref": "m_charles.wav",
                                       "models": {"multilingual": {"voice_ref": "f_mei.wav"},
                                                  "standard": {"voice_gender": "female"}}}})
    assert voice_is_female(cfg) is True                       # from the multilingual sample's f_ prefix
    cfg["tts"]["chatterbox"]["model"] = "turbo"
    assert voice_is_female(cfg) is False                      # engine sample m_…
    cfg["tts"]["chatterbox"]["model"] = "standard"
    assert voice_is_female(cfg) is True                       # forced for that model
    cfg = cfg_with(tts={"backend": "kokoro", "kokoro": {"voice": "bm_george", "voice_gender": "female"}})
    assert voice_is_female(cfg) is True                       # engine-level override wins over the voice name


def test_stt_per_model_block():
    cfg = cfg_with(stt={"backend": "faster_whisper",
                        "faster_whisper": {"model": "large-v3", "compute_type": "float16", "language": None,
                                           "models": {"large-v3": {"compute_type": "int8_float16"}}}})
    o = engine_opts(cfg, "stt")
    assert o["compute_type"] == "int8_float16" and o["language"] is None


def test_kokoro_accent_follows_voice():
    from alveus.tts.kokoro_tts import KokoroTTS
    assert KokoroTTS({"voice": "bf_emma"}).lang_code == "b"
    assert KokoroTTS({"voice": "af_heart", "lang_code": None}).lang_code == "a"
    assert KokoroTTS({"voice": "bf_emma", "lang_code": "a"}).lang_code == "a"   # explicit wins


def test_server_args_apply_context_and_gpu_layers():
    serve = {"args": ["-ngl", "99", "-c", "32768", "--jinja"]}
    assert context_of(serve) == 32768
    assert server_args({**serve, "context": 65536}) == ["-ngl", "99", "-c", "65536", "--jinja"]
    assert server_args({"args": ["--jinja"], "context": 8192, "gpu_layers": 20}) == ["--jinja", "-c", "8192", "-ngl", "20"]
    assert context_of({"args": [], "context": 4096}) == 4096 and context_of({}) is None


def test_local_gguf_discovery(tmp_path):
    (tmp_path / "qwen").mkdir()
    (tmp_path / "qwen" / "Qwen3.8-27B-Q4_K_M.gguf").write_bytes(b"x" * 10)
    (tmp_path / "qwen" / "mmproj-Qwen3.8-27B-f16.gguf").write_bytes(b"x")
    files = catalog.local_files(str(tmp_path))
    assert [f["id"] for f in files] == ["qwen3.8-27b-q4_k_m"]
    assert files[0]["portable"] == "${ALVEUS_MODELS}/qwen/Qwen3.8-27B-Q4_K_M.gguf"


def test_llm_folder_is_scanned_and_drafters_are_skipped(tmp_path):
    (tmp_path / "wakeword").mkdir()
    (tmp_path / "wakeword" / "stray.gguf").write_bytes(b"x")          # outside llm/: not listed
    d = tmp_path / "llm" / "lfm"
    d.mkdir(parents=True)
    for f in ("LFM2.5-24B-A2B-GSQ-RCO-IQ4_XS.gguf", "LFM2.5-24B-A2B-DSpark-Q8_0.gguf", "mmproj-BF16.gguf",
              "Qwen3.8-27B-FastMTP-32K.gguf", "mtp-Qwen3.8-27B-Q4_0.gguf"):
        (d / f).write_bytes(b"x")
    files = catalog.local_files(str(tmp_path))
    assert [f["file"] for f in files] == ["LFM2.5-24B-A2B-GSQ-RCO-IQ4_XS.gguf"]
    assert files[0]["portable"] == "${ALVEUS_MODELS}/llm/lfm/LFM2.5-24B-A2B-GSQ-RCO-IQ4_XS.gguf"
    assert catalog.llm_dir(str(tmp_path)) == tmp_path / "llm"


def test_shipped_local_profiles_have_aliases_and_dotless_names():
    from alveus.api import _profile_info
    cfg = load_config()
    info = _profile_info(cfg)
    local = {n: s for n, s in info.items() if s.get("local_server")}
    assert {"bonsai2-ternary", "lfm25-moe", "lfm3-small", "qwen38-direct", "qwen38-coder", "qwen38-abliterated"} <= set(local)
    for n, s in local.items():
        assert "." not in n and s["alias"] and s["label"].startswith(s["alias"])   # GUI paths split on dots
        assert "/llm/" in s["model_path"]
    aliases = [s["alias"] for s in local.values()]
    assert len(set(aliases)) == len(aliases)
    assert not any(w in a.lower() for a in aliases for w in ("heretic", "turbo", "max", "hauhau", "davidau"))
    # the modified models say so (the Qwen variants by how they differ: direct, coder merge, abliterated)
    assert all(info[n]["alias"].endswith("· uncensored") for n in ("bonsai2-ternary", "lfm25-moe", "lfm3-small"))


def test_model_list_falls_back_to_suggestions(monkeypatch, tmp_path):
    monkeypatch.setenv("ALVEUS_SECRETS", str(tmp_path / "none.env"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    res = asyncio.run(catalog.provider_models(load_config(), "anthropic"))
    assert res["source"] == "suggested" and "ANTHROPIC_API_KEY" in res["error"]
    assert res["models"][0]["id"] == "claude-opus-5-5"


def test_live_list_keeps_suggested_order_and_notes(monkeypatch):
    async def fake_live(provider, base_url, key):
        return [("deepseek-flash", ""), ("deepseek-v4-pro", "")]
    monkeypatch.setattr(catalog, "_live", fake_live)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-x")
    catalog._CACHE.clear()
    res = asyncio.run(catalog.provider_models(load_config(), "deepseek"))
    assert res["source"] == "live" and [m["id"] for m in res["models"]] == ["deepseek-v4-pro", "deepseek-flash"]
    assert res["models"][0]["note"] == "stronger reasoning"
    catalog._CACHE.clear()


def test_providers_info_has_defaults_for_new_profiles():
    from alveus.api import _providers_info
    info = _providers_info(load_config())
    assert info["anthropic"]["defaults"]["temperature"] is None          # never sent to Claude
    assert info["llama_server"]["defaults"]["temperature"] == 0.7
    assert info["llama_server"]["serve_template"]["context"] == 32768
    assert info["deepseek"]["effort_levels"] == ["low", "high", "max"]
