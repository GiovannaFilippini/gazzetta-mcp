"""Word handling shared by the local search and the archive search."""

from __future__ import annotations

STOPWORDS = frozenset(
    "a ad al alla alle agli ai allo con da dal dalla dalle dei del della delle degli di e ed "
    "gli i il in la le lo nel nella nelle nei negli o per su sul sulla sulle sui tra fra un "
    "uno una l d".split()
)


def stem(word: str) -> str:
    """Crude Italian stem: drop the final vowel so singular and plural share a prefix."""
    return word[:-1] if len(word) >= 5 and word[-1] in "aeio" else word
