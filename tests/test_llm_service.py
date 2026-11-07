"""The assistant keeps the local LLM server in line with the profile (systemd calls are mocked)."""
from alveus.config import load_config, llm_profile
from alveus.llm import service
from alveus.llm.service import plan


def test_plan_table():
    # cloud / external profile: the local server only costs VRAM
    assert plan(False, "active", None, "deepseek-v4-pro") == "stop"
    assert plan(False, "activating", None, "x") == "stop"
    assert plan(False, "inactive", None, "x") is None
    # local profile
    assert plan(True, "inactive", None, "bonsai-27b-ternary") == "start"
    assert plan(True, "failed", None, "bonsai-27b-ternary") == "start"
    assert plan(True, "active", ["bonsai-27b-1bit"], "bonsai-27b-ternary") == "restart"
    assert plan(True, "active", ["bonsai-27b-ternary"], "bonsai-27b-ternary") is None
    assert plan(True, "active", None, "bonsai-27b-ternary") is None      # still loading: leave it
    # unit not installed (another machine, no systemd): never touch anything
    assert plan(False, None, None, "x") is None and plan(True, None, None, "x") is None


def _fake(monkeypatch, state, served):
    calls = []
    monkeypatch.setattr(service, "unit_state", lambda: state)
    monkeypatch.setattr(service, "served_models", lambda base_url: served)
    monkeypatch.setattr(service.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    return calls


def test_cloud_profile_stops_the_unit(monkeypatch):
    monkeypatch.delenv("ALVEUS_LLM_PROFILE", raising=False)
    calls = _fake(monkeypatch, "active", None)
    cfg = load_config()
    assert service.reconcile_local_server(cfg, llm_profile(cfg, "deepseek")) == "stop"
    assert calls == [["systemctl", "--user", "--no-block", "stop", "alveus-llm.service"]]


def test_local_profile_with_wrong_model_restarts(monkeypatch):
    monkeypatch.delenv("ALVEUS_LLM_PROFILE", raising=False)
    calls = _fake(monkeypatch, "active", ["bonsai-27b-1bit"])
    cfg = load_config()
    assert service.reconcile_local_server(cfg, llm_profile(cfg, "bonsai-ternary")) == "restart"
    assert calls[0][-2:] == ["restart", "alveus-llm.service"]


def test_override_and_switch_off_leave_the_unit_alone(monkeypatch):
    calls = _fake(monkeypatch, "active", None)
    cfg = load_config()
    monkeypatch.setenv("ALVEUS_LLM_PROFILE", "deepseek")     # alveus talk --profile deepseek
    assert service.reconcile_local_server(cfg, llm_profile(cfg, "deepseek")) is None
    monkeypatch.delenv("ALVEUS_LLM_PROFILE")
    cfg["llm"]["manage_local_server"] = False
    assert service.reconcile_local_server(cfg, llm_profile(cfg, "deepseek")) is None
    assert calls == []
