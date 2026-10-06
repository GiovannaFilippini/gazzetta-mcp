"""Result page of the GU advanced search (``/do/ricerca/atto/serie_generale/originario/0``)."""

from __future__ import annotations

import re
from datetime import date

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..models import SearchHit, Serie
from ._util import decode, eli_id, https, split_trailing_code, squash

_CODICE = re.compile(
    r"atto\.dataPubblicazioneGazzetta=(\d{4})-(\d{2})-(\d{2})&(?:amp;)?"
    r"atto\.codiceRedazionale=([0-9A-Z]+)"
)
_COUNT = re.compile(r"Risultati della ricerca:\s*(\d+)\s*atti")
_RIFERIMENTO = re.compile(r"GU n\.\s*(\d+)")


def parse_ricerca(raw: bytes, base_url: str) -> tuple[list[SearchHit], int]:
    """Return (hits, total shown by the site). An unrecognised page gives ``([], 0)``."""
    if not raw or not raw.strip():
        return [], 0
    html = decode(raw)
    tree = HTMLParser(html)
    m = _COUNT.search(squash(tree.text()))
    total = int(m.group(1)) if m else 0
    hits: list[SearchHit] = []
    seen: set[str] = set()
    for node in tree.css("span.risultato"):
        anchors = node.css("a")
        if len(anchors) < 2:
            continue
        link = _CODICE.search(anchors[0].attributes.get("href") or "")
        if not link or link[4] in seen:
            continue
        seen.add(link[4])
        estremi = squash(anchors[0].text())
        rif = anchors[1].css_first("span.riferimento")
        riferimento = squash(rif.text()) if rif else ""
        for sub in anchors[1].css("span"):
            sub.decompose()
        titolo, _ = split_trailing_code(anchors[1].text(deep=True))
        y, mo, d = int(link[1]), int(link[2]), int(link[3])
        gu = _RIFERIMENTO.search(riferimento)
        hits.append(
            SearchHit(
                codice=link[4],
                serie=Serie.SG,
                data=date(y, mo, d),
                titolo=f"{estremi}: {titolo}" if estremi else titolo,
                estratto=riferimento.strip("()") if gu else "",
                link=eli_id(https(base_url), y, mo, d, link[4], "SG"),
                punteggio=0.0,
                origine="ricerca_gu",
            )
        )
    return hits, max(total, len(hits))
