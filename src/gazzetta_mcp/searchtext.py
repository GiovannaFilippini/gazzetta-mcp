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


# Everyday words that acts do not use: the words the Gazzetta uses instead (the "auto" family).
_AUTO = ("veicoli", "autoveicoli", "autovetture")
SYNONYMS: dict[str, tuple[str, ...]] = {
    w: _AUTO
    for w in (
        "auto",
        "automobile",
        "automobili",
        "autovettura",
        "autovetture",
        "macchina",
        "macchine",
    )
}


def word_groups(text: str) -> list[list[str]]:
    """One group per query word: the word itself followed by its synonyms."""
    return [[w, *SYNONYMS.get(w, ())] for w in search_words(text)]


def flatten(groups: list[list[str]]) -> list[str]:
    """Every distinct word of the groups, in order."""
    return list(dict.fromkeys(w for g in groups for w in g))


def count_matches(title: str, groups: list[list[str]]) -> int:
    """How many query words (or one of their synonyms) the title contains."""
    low = title.lower()
    return sum(1 for g in groups if any(stem(w) in low for w in g))
