import alveus.config as c


def test_patch_merge_and_remove(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "LOCAL_YAML", tmp_path / "local.yaml")
    c.write_local_yaml("assistant:\n  user_name: Charles\naudio:\n  backend: pipewire\n")
    merged = c.patch_local_yaml({"tts": {"kokoro": {"voice": "am_michael"}}, "audio": {"backend": None}})
    assert merged == {"assistant": {"user_name": "Charles"}, "tts": {"kokoro": {"voice": "am_michael"}}}
    merged = c.patch_local_yaml({"tts": {"kokoro": {"voice": None}}})
    assert "tts" not in merged  # empty branches are pruned
    text = c.read_local_yaml()
    assert "user_name: Charles" in text


def test_write_rejects_non_mapping(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "LOCAL_YAML", tmp_path / "local.yaml")
    try:
        c.write_local_yaml("- just\n- a list\n")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_set_path():
    assert c.set_path({}, "a.b.c", 1) == {"a": {"b": {"c": 1}}}
