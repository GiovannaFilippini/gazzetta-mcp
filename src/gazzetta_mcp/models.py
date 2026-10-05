"""Shared data structures. No dependencies on the other modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import NamedTuple

DISCLAIMER = (
    "Fonte: Gazzetta Ufficiale della Repubblica Italiana (gazzettaufficiale.it). "
    "Testo non ufficiale e non autentico, consultabile gratuitamente: fa fede solo il testo "
    "pubblicato nella Gazzetta Ufficiale. / Unofficial, non-authentic copy: only the text "
    "published in the Gazzetta Ufficiale is authoritative."
)


class Serie(str, Enum):
    SG = "SG"  # Serie Generale
    S1 = "S1"  # Corte Costituzionale
    S2 = "S2"  # Unione Europea
    S3 = "S3"  # Regioni
    S4 = "S4"  # Concorsi ed esami
    S5 = "S5"  # Contratti pubblici
    P2 = "P2"  # Parte II (inserzioni)


# Path segment used by /atto/<segment>/caricaArticoloDefault/... Verified: SG, S1, S3, S4.
# S2, S5, P2: no such frame found on act pages (see docs/fonti.md); None = unsupported.
ATTO_URL_SEGMENT: dict[Serie, str | None] = {
    Serie.SG: "serie_generale",
    Serie.S4: "concorsi",
    Serie.S1: "corte_costituzionale",
    Serie.S2: None,
    Serie.S3: "regioni",
    Serie.S5: None,
    Serie.P2: None,
}


@dataclass(frozen=True)
class RawPage:
    url: str
    content: bytes
    content_type: str
    fetched_at: datetime
    from_cache: bool = False


@dataclass(frozen=True)
class FeedItem:
    codice: str
    serie: Serie
    data: date
    titolo: str
    riassunto: str
    link: str
    pubblicato: datetime | None = None


@dataclass(frozen=True)
class Feed:
    serie: Serie
    numero: int
    data: date
    link: str
    items: list[FeedItem] = field(default_factory=list)


@dataclass(frozen=True)
class SommarioVoce:
    codice: str
    titolo: str
    emettitore: str
    rubrica: str
    link: str
    tipo: str | None = None


@dataclass(frozen=True)
class Sommario:
    serie: Serie
    data: date
    numero: int
    link: str
    link_pdf: str
    voci: list[SommarioVoce] = field(default_factory=list)


@dataclass(frozen=True)
class Atto:
    codice: str
    serie: Serie
    data: date
    titolo: str
    emettitore: str
    tipo: str | None
    testo: str
    link: str
    numero_gu: int | None = None
    scaricato_il: datetime | None = None


@dataclass(frozen=True)
class SearchFilters:
    serie: Serie | None = None
    tipo: str | None = None
    dal: date | None = None
    al: date | None = None
    limite: int = 20
    solo_vigenti: bool = False  # archives: leave out acts already repealed


@dataclass(frozen=True)
class SearchHit:
    codice: str
    serie: Serie
    data: date
    titolo: str
    estratto: str
    link: str
    punteggio: float = 0.0
    origine: str = "cache"  # where the hit comes from: cache | normattiva | ricerca_gu


class ArchiveResult(NamedTuple):
    """Outcome of an archive search."""

    hits: list[SearchHit]
    totale: int  # acts found by the archive before leaving out the repealed ones
    note: list[str]


@dataclass(frozen=True)
class NormattivaLink:
    atto: str
    urn: str
    link: str
    nota: str = ""
