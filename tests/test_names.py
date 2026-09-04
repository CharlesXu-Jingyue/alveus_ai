from alveus.audio.names import NameMatcher

m = NameMatcher(["Alveus", "Aurea"], ["alvius", "auria", "orea"])


def test_name_then_command():
    assert m.match("Alveus, what time is it?") == (True, "what time is it")
    assert m.match("Hey Aurea open firefox") == (True, "open firefox")
    assert m.match("Alvius.") == (True, "")


def test_fuzzy():
    assert m.match("Auria, turn the volume down")[0]
    assert m.match("Al vius what's the weather")[0]


def test_not_addressed():
    assert m.match("what time is it") == (False, "")
    assert m.match("the area is large") == (False, "")
    assert m.match("I like oreos") == (False, "")
