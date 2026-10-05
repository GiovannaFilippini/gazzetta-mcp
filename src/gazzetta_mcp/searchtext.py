"""Word handling shared by the local search and the archive search."""

from __future__ import annotations

import re

_WORD = re.compile(r"\w+", re.UNICODE)

STOPWORDS = frozenset(
    [
        "a",
        "ad",
        "al",
        "alla",
        "alle",
        "agli",
        "ai",
        "allo",
        "con",
        "da",
        "dal",
        "dalla",
        "dalle",
        "dei",
        "del",
        "della",
        "delle",
        "degli",
        "di",
        "e",
        "ed",
        "gli",
        "i",
        "il",
        "in",
        "la",
        "le",
        "lo",
        "nel",
        "nella",
        "nelle",
        "nei",
        "negli",
        "o",
        "per",
        "su",
        "sul",
        "sulla",
        "sulle",
        "sui",
        "tra",
        "fra",
        "un",
        "uno",
        "una",
        "l",
        "d",
    ]
)


def stem(word: str) -> str:
    """Crude Italian stem: drop the final vowel so singular and plural share a prefix."""
    return word[:-1] if len(word) >= 5 and word[-1] in "aeio" else word


def search_words(text: str) -> list[str]:
    """Meaningful words of a query: lowercase, no stopwords (kept if nothing else is left)."""
    words = [w.lower() for w in _WORD.findall(text)]
    return [w for w in words if w not in STOPWORDS] or words
