"""Detect the assistant's names at the start of a transcript (fuzzy, STT-tolerant)."""
from __future__ import annotations

import difflib
import re

_PUNCT = re.compile(r"[^\w\s']+")
_LEAD = re.compile(r"^(hey|hi|hello|ok|okay|yo|um|uh|so|excuse me)\s+", re.IGNORECASE)


class NameMatcher:
    def __init__(self, names: list[str], aliases: list[str] | None = None, cutoff: float = 0.78):
        self.names = [n.lower() for n in names]
        self.targets = sorted({*self.names, *[a.lower() for a in (aliases or [])]})
        self.cutoff = cutoff

    def _is_name(self, token: str) -> bool:
        token = token.lower().strip("'")
        if not token or len(token) < 3:
            return False
        if token in self.targets:
            return True
        return bool(difflib.get_close_matches(token, self.targets, n=1, cutoff=self.cutoff))

    def match(self, transcript: str) -> tuple[bool, str]:
        """Returns (addressed, remaining_command). Looks at the first two words, and at the
        two-word join (STT sometimes splits 'al vius')."""
        text = _PUNCT.sub(" ", transcript).strip()
        text = _LEAD.sub("", text)
        words = text.split()
        if not words:
            return False, ""
        for n in (1, 2):
            if len(words) >= n:
                cand = "".join(words[:n])
                if self._is_name(cand):
                    rest = " ".join(words[n:]).strip()
                    return True, _LEAD.sub("", rest)
        # name as the last word ("what time is it, Aurea?")
        if len(words) >= 2 and self._is_name(words[-1]):
            return True, " ".join(words[:-1]).strip()
        return False, ""
