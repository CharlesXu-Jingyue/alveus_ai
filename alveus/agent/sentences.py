"""Incremental sentence splitter for streaming text-to-speech."""
from __future__ import annotations

import re

_END = re.compile(r'([.!?]+["\')\]]*)(\s+|$)|([。！？；]+[」』）”]*)')
_ABBREV = re.compile(r"\b(e\.g|i\.e|etc|vs|Dr|Mr|Mrs|Ms|St|No|Fig|approx)\.$", re.IGNORECASE)


class SentenceBuffer:
    def __init__(self, min_chars: int = 24, max_chars: int = 360):
        self.buf = ""
        self.min_chars = min_chars
        self.max_chars = max_chars

    def feed(self, text: str) -> list[str]:
        self.buf += text
        out: list[str] = []
        while True:
            m = None
            for m_ in _END.finditer(self.buf):
                cjk = m_.group(3) is not None
                end = m_.end(3) if cjk else m_.end(1)
                cand = self.buf[:end]
                min_chars = 6 if cjk else self.min_chars
                if len(cand) >= min_chars and (cjk or (not _ABBREV.search(cand) and not _looks_like_decimal(self.buf, m_))):
                    m = (m_, end)
                    break
            if m is None:
                break
            m_, end = m
            out.append(self.buf[:end].strip())
            self.buf = self.buf[m_.end():]
        # very long run without punctuation -> split at last comma/space
        if len(self.buf) > self.max_chars:
            cut = max(self.buf.rfind(", ", 0, self.max_chars), self.buf.rfind(" ", 0, self.max_chars))
            if cut > self.min_chars:
                out.append(self.buf[:cut].strip())
                self.buf = self.buf[cut:].lstrip()
        return [s for s in out if s]

    def flush(self) -> list[str]:
        s, self.buf = self.buf.strip(), ""
        return [s] if s else []


def _looks_like_decimal(buf: str, m: re.Match) -> bool:
    i = m.start(1)
    return buf[i] == "." and i > 0 and buf[i - 1].isdigit() and m.end() < len(buf) and buf[m.end()].isdigit()


_MD = [
    (re.compile(r"```.*?```", re.DOTALL), " (code omitted) "),
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"\*\*|__|(?<!\w)\*(?!\s)|(?<!\s)\*(?!\w)|_"), ""),
    (re.compile(r"^#{1,6}\s*", re.MULTILINE), ""),
    (re.compile(r"^\s*[-*•]\s+", re.MULTILINE), ""),
    (re.compile(r"\[([^\]]+)\]\([^)]+\)"), r"\1"),
    (re.compile(r"https?://\S+"), "a link"),
    # emoji, pictographs, dingbats, symbols and variation selectors: TTS engines choke on them
    (re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF\uFE0F\u200D\u2B50\u2B55\u231A-\u23FF]"), ""),
]
_HAS_WORD = re.compile(r"[\w\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def has_speech(text: str) -> bool:
    """True if there is anything a TTS engine can pronounce (letters, digits, ideographs)."""
    return bool(_HAS_WORD.search(text or ""))


def speakable(text: str) -> str:
    """Strip markdown/code so TTS reads naturally."""
    for rx, rep in _MD:
        text = rx.sub(rep, text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if has_speech(text) else ""
