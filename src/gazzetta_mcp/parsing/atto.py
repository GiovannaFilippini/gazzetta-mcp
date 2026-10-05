"""A single act: the "scheda" page (headings) plus the text page (<pre> body)."""

from __future__ import annotations

import re
from datetime import date

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..models import Atto, Serie
from ._util import decode, eli_id, split_trailing_code, squash
from .text import clean_text, extract_export, extract_pre
from .tipo import detect_tipo

_GU_NUMBER = re.compile(r"\(GU[^)]*?n\.\s*(\d+)\s+del", re.IGNORECASE)


def parse_atto(
    scheda: bytes,
    testo: bytes,
    codice: str,
    serie: Serie,
    data: date,
    base_url: str,
    raw_text: bool = False,
) -> Atto:
    """Combine the scheda and the text page. Missing parts give empty strings, never errors."""
    emettitore = tipo_line = descrizione = ""
    numero_gu: int | None = None
    if scheda and scheda.strip():
        html = decode(scheda)
        tree = HTMLParser(html)
        h1 = tree.css_first("h1.consultazione")
        h2 = tree.css_first("h2.consultazione")
        h3 = tree.css_first("h3.consultazione")
        emettitore = squash(h1.text()) if h1 else ""
        tipo_line = squash(h2.text()) if h2 else ""
        if h3 is not None:
            span = h3.css_first('span[property="eli:title"]')
            descrizione, _ = split_trailing_code(span.text() if span else _h3_own_text(h3))
        m = _GU_NUMBER.search(html)
        numero_gu = int(m.group(1)) if m else None

    titolo = " - ".join(p for p in (tipo_line, descrizione) if p)
    tipo = detect_tipo(tipo_line) or detect_tipo(titolo)
    raw_body = (extract_export(testo) or extract_pre(testo)) if testo else ""
    body = clean_text(raw_body, raw=raw_text) if raw_body else ""
    return Atto(
        codice=codice,
        serie=serie,
        data=data,
        titolo=titolo,
        emettitore=emettitore,
        tipo=tipo,
        testo=body,
        link=eli_id(base_url, data.year, data.month, data.day, codice, serie.value),
        numero_gu=numero_gu,
    )


def _h3_own_text(h3) -> str:
    for sub in h3.css("span"):
        sub.decompose()
    return h3.text()
