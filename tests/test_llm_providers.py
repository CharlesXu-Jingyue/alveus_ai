"""Provider presets, profile resolution, API-key storage and what tool servers get to see."""
import os
import stat

import pytest

from alveus import credentials
from alveus.agent.mcp_client import ToolHub, hub_env, secret_env_names
from alveus.config import load_config, llm_profile
from alveus.llm import make_llm
from alveus.llm.providers import is_remote, resolve

LLM = {"temperature": 0.7, "top_p": 0.95, "max_tokens": 4096, "effort": None, "max_tool_rounds": 12}


def test_preset_supplies_protocol_address_and_key_variable():
    p = resolve("c", {"provider": "anthropic", "model": "claude-opus-5-5"}, LLM)
    assert p["api"] == "anthropic_messages" and p["api_key_env"] == "ANTHROPIC_API_KEY"
    assert p["remote"] is True and p["max_tokens"] == 4096
    # Claude rejects sampling parameters: the llm-level defaults are dropped ...
    assert "temperature" not in p and "top_p" not in p
    # ... unless the profile itself asks for them (older models)
    p = resolve("c", {"provider": "anthropic", "model": "x", "temperature": 0.2}, LLM)
    assert p["temperature"] == 0.2


def test_profile_overrides_llm_level_and_preset():
    p = resolve("d", {"provider": "deepseek", "model": "deepseek-v4-pro", "max_tokens": 16000,
                      "base_url": "https://proxy.example/v1"}, LLM)
    assert p["max_tokens"] == 16000 and p["base_url"] == "https://proxy.example/v1"
    assert p["reasoning_replay"] == "all" and p["temperature"] == 0.7


def test_legacy_backend_key_still_works():
    p = resolve("old", {"backend": "openai", "base_url": "http://127.0.0.1:8080/v1", "model": "m"}, LLM)
    assert p["provider"] == "openai_compat" and p["api"] == "openai_chat" and p["remote"] is False


def test_unknown_provider_needs_api_and_base_url():
    with pytest.raises(KeyError):
        resolve("x", {"provider": "acme", "model": "m"}, LLM)
    p = resolve("x", {"provider": "acme", "api": "openai_chat", "base_url": "https://acme.ai/v1", "model": "m"}, LLM)
    assert p["label"] == "acme" and p["remote"] is True


def test_is_remote():
    assert not is_remote("http://127.0.0.1:8080/v1") and not is_remote("http://localhost:11434/v1")
    assert is_remote("https://api.deepseek.com") and is_remote(None)


def test_shipped_profiles_resolve_and_build():
    cfg = load_config()
    for name in cfg.llm.profiles:
        prof = llm_profile(cfg, name)
        llm = make_llm(prof)
        assert llm.model == prof.model and llm.remote == prof.remote


def test_secrets_file_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "alveus" / "secrets.env"
    monkeypatch.setenv("ALVEUS_SECRETS", str(path))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert credentials.get("DEEPSEEK_API_KEY") is None
    credentials.set_secret("DEEPSEEK_API_KEY", "sk-test-123")
    assert credentials.get("DEEPSEEK_API_KEY") == "sk-test-123"
    assert credentials.source("DEEPSEEK_API_KEY") == "file"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "DEEPSEEK_API_KEY" not in os.environ          # never exported to child processes
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")     # the environment wins
    assert credentials.get("DEEPSEEK_API_KEY") == "from-env" and credentials.source("DEEPSEEK_API_KEY") == "env"
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    credentials.set_secret("DEEPSEEK_API_KEY", "")
    assert credentials.get("DEEPSEEK_API_KEY") is None
    with pytest.raises(ValueError):
        credentials.set_secret("bad name", "x")
    with pytest.raises(ValueError):
        credentials.set_secret("OK_NAME", "two\nlines")


def test_api_key_for_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("ALVEUS_SECRETS", str(tmp_path / "s.env"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert credentials.api_key_for({"api_key_env": "OPENAI_API_KEY"}) == "sk-env"
    assert credentials.api_key_for({"api_key": "local", "api_key_env": "OPENAI_API_KEY"}) == "local"


def test_tool_servers_do_not_inherit_api_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    hub = ToolHub({}, "/repo")
    assert "ANTHROPIC_API_KEY" not in hub.server_env({})
    assert hub.server_env({"inherit_api_keys": True})["ANTHROPIC_API_KEY"] == "sk-secret"
    assert {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"} <= secret_env_names()


def test_hub_env_tells_the_coder_which_model_auto_means():
    cfg = load_config()
    cfg["llm"]["profile"] = "claude"
    env = hub_env(cfg)
    assert env["ALVEUS_OPENCODE_AUTO"] == "anthropic/claude-opus-5-5" and env["ALVEUS_LLM_PROVIDER"] == "anthropic"
    cfg["llm"]["profile"] = "bonsai-1bit"
    env = hub_env(cfg)
    assert env["ALVEUS_OPENCODE_AUTO"] == "" and env["ALVEUS_LLM_MODEL"] == "bonsai-27b-1bit"
    assert not any("sk-" in v for v in env.values())


def test_files_tool_refuses_the_key_folder(monkeypatch, tmp_path):
    import importlib
    monkeypatch.setenv("ALVEUS_SECRETS", str(tmp_path / "keys" / "secrets.env"))
    monkeypatch.setenv("ALVEUS_FS_ROOTS", str(tmp_path))
    (tmp_path / "keys").mkdir()
    (tmp_path / "keys" / "secrets.env").write_text("DEEPSEEK_API_KEY=sk-should-not-leak\n")
    (tmp_path / "notes.txt").write_text("sk-should-not-leak is mentioned here too\n")
    import mcp_servers.files_shell as fs
    fs = importlib.reload(fs)
    # tool errors come back as {"error": ...} replies (mcp_servers/common.py), never with the content
    out = fs.read_file(str(tmp_path / "keys" / "secrets.env"))
    assert "API keys" in out and "sk-should-not-leak" not in out
    assert "Refused" in fs.list_dir(str(tmp_path / "keys"))
    assert "Refused" in fs.find_files("*.env", str(tmp_path / "keys"))
    hits = __import__("json").loads(fs.search_text("sk-should-not-leak", str(tmp_path)))["hits"]
    assert [h["file"] for h in hits] == [str(tmp_path / "notes.txt")]     # the key folder is skipped
    assert "Refused" in fs.run_command("cat ~/.config/alveus/secrets.env", str(tmp_path))
    assert "Refused" in fs.run_command(f"grep -r sk {tmp_path / 'keys'}", str(tmp_path))
    assert "Refused" not in fs.run_command("echo ok", str(tmp_path))
