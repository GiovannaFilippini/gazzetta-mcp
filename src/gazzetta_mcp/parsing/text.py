"""Cleaning of the fixed-width <pre> text of a GU act for LLM reading.

Every rule is documented in docs/decisioni/020-pulizia-testo.md. The cleaning only
re-flows whitespace: it never changes, adds or drops words, digits or punctuation,
except for removing a hyphen at end of line when the split word is clearly proven
(see ``_Hyphens``). ``raw=True`` returns the text exactly as extracted.
"""

from __future__ import annotations

import re

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ._util import decode

# A line indented at least this much is a centered heading ("Art. 1", "Decreta:").
CENTERED_MIN_INDENT = 10

_WORD = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")
_SPLIT_END = re.compile(r"[^\W_]-$")
_LIST_MARKER = re.compile(r"^(?:[a-z]{1,2}\)|\d{1,3}\)|\d{1,3}\.|[-•*])\s+\S")
_SENTENCE_END = (".", ";", ":", "?", "!")
_MULTISPACE = re.compile(r" {2,}")


def extract_pre(testo_html: bytes | str) -> str:
    """Return the unmodified text of the first non-empty <pre> block ("" if none).

    If the page has no <pre> at all, falls back to the text of <body>.
    """
    html = testo_html if isinstance(testo_html, str) else decode(testo_html)
    if not html.strip():
        return ""
    tree = HTMLParser(html)
    for pre in tree.css("pre"):
        text = pre.text(deep=True, strip=False)
        if text.strip():
            return text
    body = tree.body
    text = body.text(deep=True, strip=False) if body is not None else ""
    return text if text.strip() else ""


class _Hyphens:
    """Knows which words appear whole in the document, to prove a split word."""

    def __init__(self, lines: list[str]) -> None:
        plain: set[str] = set()
        skip_first = False
        for line in lines:
            toks = list(_WORD.finditer(line.strip()))
            ends_split = bool(_SPLIT_END.search(line.rstrip()))
            for i, m in enumerate(toks):
                if i == 0 and skip_first:
                    continue
                if i == len(toks) - 1 and ends_split:
                    continue
                if "-" not in m.group(0):
                    plain.add(m.group(0).lower())
            skip_first = ends_split
        self.plain = plain

    def join(self, left: str, right: str) -> str:
        """Join two lines where ``left`` ends with a hyphen. Returns the merged text."""
        lm = re.search(r"([^\W\d_]+)-$", left)
        rm = re.match(r"([^\W\d_]+)", right)
        if lm and rm and right[:1].islower():
            whole = (lm.group(1) + rm.group(1)).lower()
            if whole in self.plain:
                return left[:-1] + right  # proven split word: drop the hyphen
        if left[-2:-1].isalnum() and right[:1].isalnum():
            return left + right  # keep the hyphen: compound or unproven split
        return left + " " + right


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def clean_text(pre: str, raw: bool = False) -> str:
    """Turn the hard-wrapped <pre> text into readable paragraphs.

    ``raw=True`` returns ``pre`` untouched (rollback switch).
    """
    if raw:
        return pre
    text = pre.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ").expandtabs(8)
    lines = [ln.rstrip() for ln in text.split("\n")]
    hyph = _Hyphens(lines)

    # Each paragraph: (is_centered, [lines]).
    paras: list[tuple[bool, list[str]]] = []
    current: tuple[bool, list[str]] | None = None
    prev_line = ""
    for line in lines:
        if not line.strip():
            current = None
            prev_line = ""
            continue
        indent = _indent(line)
        body = line.strip()
        if indent >= CENTERED_MIN_INDENT:
            if current is None or not current[0]:
                current = (True, [])
                paras.append(current)
            current[1].append(body)
        else:
            starts_new = (
                current is None
                or current[0]
                or indent > 0
                or (bool(_LIST_MARKER.match(body)) and prev_line.endswith(_SENTENCE_END))
            )
            if starts_new:
                current = (False, [])
                paras.append(current)
            assert current is not None
            current[1].append(body)
        prev_line = body

    out: list[str] = []
    for centered, plines in paras:
        if centered:
            out.append("\n".join(_MULTISPACE.sub(" ", ln) for ln in plines))
            continue
        merged = plines[0]
        for nxt in plines[1:]:
            if _SPLIT_END.search(merged):
                merged = hyph.join(merged, nxt)
            else:
                merged = merged + " " + nxt
        out.append(_MULTISPACE.sub(" ", merged))
    return "\n\n".join(out).strip()
