"""Lightweight per-sentence language identification for multilingual TTS.

Script detection first (CJK, kana, hangul, Cyrillic, Greek, Arabic, Hebrew, Devanagari), then
`langdetect` for Latin-script text, then a configured fallback. Returns ISO 639-1 codes.
"""
from __future__ import annotations

import re

_SCRIPTS = [
    (re.compile(r"[぀-ヿ]"), "ja"),                 # hiragana / katakana
    (re.compile(r"[가-힯]"), "ko"),                 # hangul
    (re.compile(r"[一-鿿㐀-䶿]"), "zh"),    # CJK ideographs (after ja/ko checks)
    (re.compile(r"[Ѐ-ӿ]"), "ru"),
    (re.compile(r"[Ͱ-Ͽ]"), "el"),
    (re.compile(r"[؀-ۿ]"), "ar"),
    (re.compile(r"[֐-׿]"), "he"),
    (re.compile(r"[ऀ-ॿ]"), "hi"),
    (re.compile(r"[฀-๿]"), "th"),
]
_LATIN_WORD = re.compile(r"[A-Za-zÀ-ÿ]{2,}")


def detect_language(text: str, fallback: str = "en", allowed: set[str] | None = None) -> str:
    """Best-effort language code for one sentence."""
    for rx, code in _SCRIPTS:
        hits = len(rx.findall(text))
        if hits and hits >= 0.3 * max(1, len(re.sub(r"\s", "", text))):
            return code if (allowed is None or code in allowed) else fallback
    if len(_LATIN_WORD.findall(text)) >= 3:
        try:
            from langdetect import DetectorFactory, detect

            DetectorFactory.seed = 0
            code = detect(text)
            code = {"zh-cn": "zh", "zh-tw": "zh"}.get(code, code)
            if allowed is None or code in allowed:
                return code
        except Exception:  # noqa: BLE001
            pass
    return fallback
