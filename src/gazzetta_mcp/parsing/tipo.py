"""Detect the kind of provision (DECRETO, LEGGE, AVVISO...) from a GU title."""

from __future__ import annotations

import re

# Longest phrases first: "DECRETO-LEGGE" must win over "DECRETO" and "LEGGE".
TIPI: tuple[str, ...] = (
    "DECRETO-LEGGE",
    "DECRETO LEGISLATIVO",
    "DECRETO DEL PRESIDENTE DELLA REPUBBLICA",
    "DECRETO DEL PRESIDENTE DEL CONSIGLIO DEI MINISTRI",
    "LEGGE COSTITUZIONALE",
    "LEGGE REGIONALE",
    "DECRETO",
    "LEGGE",
    "DELIBERA",
    "DELIBERAZIONE",
    "ORDINANZA",
    "DETERMINA",
    "DETERMINAZIONE",
    "PROVVEDIMENTO",
    "COMUNICATO",
    "AVVISO",
    "BANDO",
    "ESTRATTO",
    "REGOLAMENTO",
    "CIRCOLARE",
    "DIRETTIVA",
    "SENTENZA",
    "RISOLUZIONE",
    "MOZIONE",
    "RETTIFICA",
    "ERRATA CORRIGE",
    "CONCORSO",
    "STATUTO",
    "TESTO COORDINATO",
)

_ALT = "|".join(re.escape(t) for t in TIPI)
_AT_START = re.compile(rf"^(?:{_ALT})(?![A-Za-z])")
_ANYWHERE = re.compile(rf"(?<![A-Za-z'])(?:{_ALT})(?![A-Za-z])")


def detect_tipo(title: str) -> str | None:
    """Return the provision type found in a title, upper case, or None.

    Titles look like ``"MINISTERO DELL'ECONOMIA - DECRETO 7 settembre 2026"`` or
    ``"DECRETO 9 settembre 2026"``. The last " - " segment is tried first, then
    the whole string (upper-case match only, so lower-case prose is ignored).
    """
    title = " ".join(title.split())
    if not title:
        return None
    last = title.rsplit(" - ", 1)[-1].strip()
    m = _AT_START.match(last)
    if m:
        return m.group(0)
    m = _ANYWHERE.search(title)
    return m.group(0) if m else None
