"""Table of contents (sommario) of one GU issue."""

from __future__ import annotations

import re
from datetime import date

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from ..models import Serie, Sommario, SommarioVoce
from ._util import decode, eli_id, https, split_trailing_code, squash
from .tipo import detect_tipo

_CODICE = re.compile(r"atto\.codiceRedazionale=([A-Za-z0-9]+)")
_DATA = re.compile(r"atto\.dataPubblicazioneGazzetta=(\d{4})-(\d{2})-(\d{2})")


def _own_text(node: Node) -> str:
    """Text of an anchor without its nested <span> blocks (page number, references)."""
    for sub in node.css("span"):
        sub.decompose()
    return node.text(deep=True)


def parse_sommario(raw: bytes, serie: Serie, data: date, numero: int, base_url: str) -> Sommario:
    """Parse the /eli/gu/.../html page. An empty or unrecognised page gives no entries."""
    root = https(base_url).rstrip("/")
    prefix = f"{root}/eli/gu/{data.year:04d}/{data.month:02d}/{data.day:02d}/{numero}/{serie.value}"
    voci: list[SommarioVoce] = []
    if raw and raw.strip():
        tree = HTMLParser(decode(raw))
        rubrica = emettitore = ""
        seen: set[str] = set()
        # rubrica / emettitore / risultato are flat siblings in document order: the
        # last rubrica and emettitore apply to the following risultato blocks.
        for node in tree.css("span.rubrica, span.emettitore, span.risultato"):
            cls = node.attributes.get("class") or ""
            if "rubrica" in cls:
                rubrica = squash(node.text())
            elif "emettitore" in cls:
                emettitore = squash(node.text())
            else:
                voce = _voce(node, serie, data, root, rubrica, emettitore)
                if voce and voce.codice not in seen:
                    seen.add(voce.codice)
                    voci.append(voce)
    return Sommario(
        serie=serie,
        data=data,
        numero=numero,
        link=f"{prefix}/html",
        link_pdf=f"{prefix}/pdf",
        voci=voci,
    )


def _voce(
    node: Node, serie: Serie, data: date, root: str, rubrica: str, emettitore: str
) -> SommarioVoce | None:
    links = node.css("a[href]")
    codice = None
    pub = data
    for a in links:
        href = a.attributes.get("href") or ""
        m = _CODICE.search(href)
        if m:
            codice = m.group(1)
            d = _DATA.search(href)
            if d:
                pub = date(int(d.group(1)), int(d.group(2)), int(d.group(3)))
            break
    if not codice:
        return None
    tipo_text = ""
    titolo = ""
    for a in links:
        data_span = a.css_first("span.data")
        if data_span is not None:
            tipo_text = squash(data_span.text())
        else:
            titolo, _ = split_trailing_code(_own_text(a))
    return SommarioVoce(
        codice=codice,
        titolo=titolo,
        emettitore=emettitore,
        rubrica=rubrica,
        link=eli_id(root, pub.year, pub.month, pub.day, codice, serie.value),
        tipo=detect_tipo(tipo_text),
    )
