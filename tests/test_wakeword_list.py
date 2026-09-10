from alveus.audio.wakeword import model_list


def test_model_list_accepts_list_string_and_empty():
    assert model_list(["alveus", "aurea"]) == ["alveus", "aurea"]
    assert model_list("alveus, aurea") == ["alveus", "aurea"]
    assert model_list("hey_jarvis") == ["hey_jarvis"]
    assert model_list("") == ["hey_jarvis"]
    assert model_list(None) == ["hey_jarvis"]
    assert model_list([" x ", ""]) == ["x"]
