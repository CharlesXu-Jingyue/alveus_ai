"""Instructions and personalities: composing the system prompt, own copies, the API and live switching."""
import asyncio
import json

import pytest

from alveus import live, personality
from alveus.agent.loop import Agent
from alveus.config import DotDict, load_config


def cfg_with(tmp_path, **assistant):
    cfg = load_config()
    # the shipped default, not whatever the owner picked in config/local.yaml
    cfg["assistant"] = {**cfg["assistant"], "personalities_dir": str(tmp_path / "own"), "personality": "calm",
                        **assistant}
    return DotDict(json.loads(json.dumps(cfg, default=str)))


def test_four_personalities_ship_with_calm_first(tmp_path):
    allp = personality.load_all(cfg_with(tmp_path))
    assert list(allp)[:4] == ["calm", "sweet", "tsundere", "genki"]
    assert all(p.shipped and not p.edited and p.description for p in allp.values())
    assert personality.active(cfg_with(tmp_path, personality=None)).id == "calm"


def test_prompt_is_instructions_plus_the_chosen_personality(tmp_path):
    calm = Agent(None, None, cfg_with(tmp_path)).system_prompt
    tsun = Agent(None, None, cfg_with(tmp_path, personality="tsundere")).system_prompt
    for p in (calm, tsun):
        assert "private system" in p and "confirmed with" in p and "{" not in p     # the instructions, filled in
        assert p.rstrip().split("\n")[-1].startswith("Today's date is")
    assert "calm, warm and unhurried" in calm and "tsundere" not in calm
    assert "You are a tsundere" in tsun and "unhurried" not in tsun
    assert "truly fond of Charles" in tsun                                   # placeholders in the personality too


def test_unknown_personality_falls_back_to_the_default(tmp_path):
    assert personality.active(cfg_with(tmp_path, personality="gone")).id == "calm"


def test_edit_a_shipped_one_then_restore_it(tmp_path):
    cfg = cfg_with(tmp_path, personality="genki")
    p = personality.save(cfg, "genki", "Genki", "louder", "You are LOUD, {user_name}! {not a placeholder}")
    assert p.edited and p.path.startswith(str(tmp_path)) and (personality.SHIPPED_DIR / "genki.md").read_text() != ""
    prompt = Agent(None, None, cfg).system_prompt
    assert "You are LOUD, Charles! {not a placeholder}" in prompt          # other braces survive
    assert list(personality.load_all(cfg))[3] == "genki"                   # keeps its place
    assert personality.remove(cfg, "genki") == "restored"
    assert not personality.load_all(cfg)["genki"].edited


def test_own_personalities(tmp_path):
    cfg = cfg_with(tmp_path)
    p = personality.save(cfg, personality.slug("Dry Butler!"), "Dry Butler!", "", "Very dry.")
    assert p.id == "dry-butler" and not p.shipped and list(personality.load_all(cfg))[-1] == "dry-butler"
    assert personality.remove(cfg, "dry-butler") == "deleted"
    with pytest.raises(ValueError):
        personality.save(cfg, "../x", "x", "", "text")
    with pytest.raises(FileNotFoundError):
        personality.remove(cfg, "calm")                                   # shipped and unedited


def test_instructions_without_the_placeholder_get_it_appended(tmp_path):
    f = tmp_path / "rules.md"
    f.write_text("You are {name}. Be brief.\n")
    text = personality.system_prompt(cfg_with(tmp_path, instructions_file=str(f), personality="sweet"), "Aurea", "Alveus", True)
    assert text.startswith("You are Aurea. Be brief.\n\nYou have a sweet")


def test_switching_personality_applies_live(tmp_path, monkeypatch):
    monkeypatch.setattr("alveus.llm.service.reconcile_local_server", lambda cfg, prof: None)
    old = cfg_with(tmp_path)
    a = type("A", (), {})()
    a.cfg, a.load_speech = old, False
    a.agent = Agent(None, None, old)
    new = cfg_with(tmp_path, personality="sweet")
    rep = asyncio.run(live.apply_config(a, new))
    assert rep["live"] == ["personality: Sweet"] and not rep["restart"]
    assert "You have a sweet" in a.agent.system_prompt


def test_api(tmp_path):
    from fastapi.testclient import TestClient

    from alveus.api import build_app
    a = type("A", (), {})()
    a.cfg = cfg_with(tmp_path, personality="sweet")
    a.agent = Agent(None, None, a.cfg)
    c = TestClient(build_app(a))
    r = c.get("/personalities").json()
    assert r["active"] == "sweet" and [i["id"] for i in r["items"]][:4] == ["calm", "sweet", "tsundere", "genki"]
    assert c.put("/personalities/mine", json={"label": "Mine", "text": "Quiet. {user_name}."}).json()["saved"]
    assert c.put("/personalities/Bad Id", json={"text": "x"}).status_code == 400
    a.cfg["assistant"]["personality"] = "mine"
    assert c.delete("/personalities/mine").status_code == 409                # in use
    a.cfg["assistant"]["personality"] = "calm"
    assert c.delete("/personalities/mine").json() == {"deleted": "mine"}
    assert c.delete("/personalities/calm").status_code == 404
    assert "{personality}" in c.get("/instructions").json()["text"]
