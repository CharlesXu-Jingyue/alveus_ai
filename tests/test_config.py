from alveus.config import llm_profile, load_config


def test_load_and_expand(monkeypatch):
    monkeypatch.setenv("ALVEUS_MODELS", "/tmp/models")
    cfg = load_config()
    prof = llm_profile(cfg, "bonsai-1bit")
    assert prof["model"]
    assert prof["serve"]["model_path"].startswith("/tmp/models")
    assert cfg.assistant.name == "Alveus"
    assert prof.base_url.startswith("http")   # from the llama_server preset


def test_profile_override(monkeypatch):
    monkeypatch.setenv("ALVEUS_LLM_PROFILE", "bonsai-ternary")
    cfg = load_config()
    assert llm_profile(cfg).name == "bonsai-ternary"
