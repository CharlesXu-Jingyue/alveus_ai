from alveus.agent.sentences import SentenceBuffer, speakable


def test_streaming_split():
    sb = SentenceBuffer(min_chars=5)
    out = []
    for chunk in ["The GPU is at 41", " degrees. It is idle", " right now! Anything", " else?"]:
        out += sb.feed(chunk)
    out += sb.flush()
    assert out == ["The GPU is at 41 degrees.", "It is idle right now!", "Anything else?"]


def test_decimal_not_split():
    sb = SentenceBuffer(min_chars=5)
    out = sb.feed("Version 3.14 is out. Yes.")
    out += sb.flush()
    assert out == ["Version 3.14 is out.", "Yes."]


def test_speakable_strips_markdown():
    assert speakable("**Bold** and `code` and [link](http://x.y) here") == "Bold and code and link here"
    assert "code omitted" in speakable("run ```bash\nls\n``` now")


def test_speakable_drops_emoji_and_empty():
    assert speakable("希望你今天过得开心！ 😊") == "希望你今天过得开心！"
    assert speakable("😊") == ""
    assert speakable("Great job! 🎉🎉") == "Great job!"
