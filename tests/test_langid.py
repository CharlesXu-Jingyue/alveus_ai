from alveus.agent.sentences import SentenceBuffer
from alveus.tts.langid import detect_language


def test_scripts():
    assert detect_language("今天天气很好。") == "zh"
    assert detect_language("こんにちは、元気ですか") == "ja"
    assert detect_language("안녕하세요 반갑습니다") == "ko"
    assert detect_language("Привет, как дела сегодня") == "ru"


def test_latin_and_fallback():
    assert detect_language("The GPU is running at forty-two degrees right now.") == "en"
    assert detect_language("Das Wetter ist heute wirklich sehr schön in Berlin.") == "de"
    assert detect_language("42", fallback="en") == "en"


def test_cjk_sentence_split():
    sb = SentenceBuffer()
    out = sb.feed("今天天气很好。我们出去走走吧！好的，") + sb.flush()
    assert out == ["今天天气很好。", "我们出去走走吧！", "好的，"]
