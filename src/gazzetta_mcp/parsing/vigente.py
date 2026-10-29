"""One article of an act in its current (vigente) form, from the Normattiva Open Data API.

The API answers with JSON; the text is a small HTML fragment (``articoloHtml``). Parts added or
replaced by later laws are wrapped in double parentheses ``(( ... ))`` by Normattiva itself:
they are kept as they are, because they are the only mark of what changed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ._util import ParseError, decode, squash

_BLOCKS = frozenset({"div", "p", "h1", "h2", "h3", "h4", "li", "ul", "ol", "table", "tr"})
_NO_END = "99999999"


class NoActError(ParseError):
    """The API answered without any act."""


@dataclass(frozen=True)
class VigenteArticolo:
    titolo: str  # e.g. "LEGGE 7 agosto 1990, n. 241"
    sottotitolo: str  # the subject of the act
    testo: str
    in_vigore_dal: date | None  # since when this wording of the article is in force
    fino_al: date | None  # None while it is still in force
    altre_versioni: int = 0  # other acts found for the same reference (0 = unambiguous)


def parse_articolo(raw: bytes) -> VigenteArticolo:
    """Parse a ``dettaglio-atto-urn`` answer. Raises ParseError on anything unexpected."""
    try:
        data = json.loads(decode(raw))
    except ValueError as exc:
        raise ParseError("Normattiva: unreadable answer") from exc
    body = data.get("data") if isinstance(data, dict) else None
    if not isinstance(body, dict):
        raise NoActError("Normattiva: no data in the answer")
    atto = body.get("atto")
    others = 0
    if not isinstance(atto, dict):
        lista = [a for a in body.get("lista") or [] if isinstance(a, dict)]
        if not lista:
            raise NoActError("Normattiva: no act found")
        atto, others = lista[0], len(lista) - 1
    html = atto.get("articoloHtml")
    if not isinstance(html, str) or not html.strip():
        raise ParseError("Normattiva: the answer has no article text")
    testo = html_to_text(html)
    if not testo:
        raise ParseError("Normattiva: the article text is empty")
    return VigenteArticolo(
        titolo=squash(str(atto.get("titolo") or "")),
        sottotitolo=squash(str(atto.get("sottoTitolo") or "")),
        testo=testo,
        in_vigore_dal=_day(atto.get("articoloDataInizioVigenza")),
        fino_al=_day(atto.get("articoloDataFineVigenza")),
        altre_versioni=others,
    )


def _day(value: object) -> date | None:
    """``"20200915"`` -> date; "0", the open end ``99999999`` and bad values -> None."""
    s = str(value or "")
    if len(s) != 8 or not s.isdigit() or s == _NO_END:
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:]))
    except ValueError:
        return None


def html_to_text(html: str) -> str:
    """Plain text with one line per block (heading, paragraph, list item); no word is changed."""
    root = HTMLParser(html).body
    if root is None:
        return ""
    out: list[str] = []
    _walk(root, out)
    lines = [squash(line) for line in "".join(out).split("\n")]
    text = "\n".join(line for line in lines if line)
    return re.sub(r"\n(?=(?:Art\.|AGGIORNAMENT[OI]))", "\n\n", text).strip()


def _walk(node, out: list[str]) -> None:
    for child in node.iter(include_text=True):
        tag = child.tag
        if tag == "-text":
            out.append(child.text_content or "")
        elif tag == "br":
            out.append("\n")
        elif tag in _BLOCKS:
            out.append("\n")
            _walk(child, out)
            out.append("\n")
        else:
            _walk(child, out)
