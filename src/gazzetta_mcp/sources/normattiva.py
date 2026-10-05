"""Builds Normattiva permalinks (URN form) from free text. No network access, no downloads."""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from ..config import Settings
from ..models import NormattivaLink

# (URN type, label, regex matched at the start of the normalised text). Order matters:
# more specific forms must come before the generic ones they start with.
_TYPES: list[tuple[str, str, str]] = [
    ("legge.costituzionale", "Legge costituzionale", r"legge costituzionale|legge cost|l ?cost"),
    (
        "regio.decreto.legislativo",
        "Regio decreto legislativo",
        r"regio decreto legislativo|r ?d ?lgs",
    ),
    ("regio.decreto.legge", "Regio decreto-legge", r"regio decreto legge|r ?d ?l"),
    ("regio.decreto", "Regio decreto", r"regio decreto|r ?d"),
    ("decreto.legislativo", "Decreto legislativo", r"decreto legislativo|d ?lgs|dlgs"),
    (
        "decreto.del.presidente.del.consiglio.dei.ministri",
        "Decreto del Presidente del Consiglio dei ministri",
        r"decreto del presidente del consiglio dei ministri|d ?p ?c ?m",
    ),
    (
        "decreto.del.presidente.della.repubblica",
        "Decreto del Presidente della Repubblica",
        r"decreto del presidente della repubblica|decreto presidente della repubblica|d ?p ?r",
    ),
    ("decreto.legge", "Decreto-legge", r"decreto legge|d ?l"),
    ("decreto.ministeriale", "Decreto ministeriale", r"decreto ministeriale|d ?m"),
    ("legge", "Legge", r"legge|l"),
]
_TYPE_RES = [(urn, label, re.compile(rf"(?:{rx})(?![a-z])")) for urn, label, rx in _TYPES]

_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "gennaio",
            "febbraio",
            "marzo",
            "aprile",
            "maggio",
            "giugno",
            "luglio",
            "agosto",
            "settembre",
            "ottobre",
            "novembre",
            "dicembre",
        ],
        start=1,
    )
}
_DATE_TEXT = re.compile(r"(?<!\d)(\d{1,2}) ?°? ?([a-z]+) (\d{4})(?!\d)")
_DATE_NUM = re.compile(r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})(?!\d)")
_NUM_LABELLED = re.compile(r"(?<![a-z])(?:n|nr|num|numero) ?\.? ?°? ?(\d+)(?!\d)")
_NUM_YEAR = re.compile(r"(?<!\d)(\d+) ?/ ?(\d{4})(?!\d)")
_NUM_BARE = re.compile(r"(?<![\d/])(\d+)(?![\d/])")
_CODICE = re.compile(r"(?<![a-z0-9])\d{2}[a-z]\d{5}(?![a-z0-9])")

MIN_YEAR = 1861
MAX_YEAR = 2100

NOTA_UFFICIALITA = (
    "Normattiva non e' una fonte ufficiale: i testi presenti nella banca dati non hanno "
    "carattere di ufficialita'. L'unico testo ufficiale e definitivo e' quello pubblicato "
    "sulla Gazzetta Ufficiale. Fonte: Normattiva (normattiva.it), testo non autentico e gratuito."
)


def _normalise(text: str) -> str:
    """Lowercase, drop accents, unify ordinal signs and punctuation, collapse spaces."""
    t = text.replace("º", "°").replace("ª", "°").replace("–", "-").replace("—", "-")
    t = "".join(c for c in unicodedata.normalize("NFD", t) if not unicodedata.combining(c))
    t = t.lower()
    t = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", t)  # decreto-legge -> decreto legge
    t = re.sub(r"(?<=[a-z])\.", " ", t)  # d.lgs. 7 -> d lgs 7
    t = t.replace(",", " ").replace(";", " ")
    return re.sub(r"\s+", " ", t).strip()


class NormattivaLinkBuilder:
    """Implements NormattivaLinker."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._base = (settings or Settings()).normattiva_base_url.rstrip("/")

    def link_for(self, atto: str) -> NormattivaLink:
        if not atto or not atto.strip():
            raise ValueError(_errore(atto))
        text = _normalise(atto)

        for urn_type, label, rx in _TYPE_RES:
            m = rx.match(text)
            if m:
                return self._build(atto, urn_type, label, text[m.end() :].strip())

        codice = _CODICE.search(text)
        if codice:
            return self._codice_link(atto, codice.group(0).upper())
        raise ValueError(_errore(atto))

    def _codice_link(self, atto: str, codice: str) -> NormattivaLink:
        nota = (
            f"Il codice redazionale {codice} da solo non identifica l'atto su Normattiva: "
            "serve tipo, data e numero (es. 'legge 5 agosto 2026, n. 140'). "
            "Ti rimando alla pagina di ricerca di Normattiva. " + NOTA_UFFICIALITA
        )
        return NormattivaLink(
            atto=atto.strip(), urn="", link=f"{self._base}/ricerca/semplice", nota=nota
        )

    def _build(self, atto: str, urn_type: str, label: str, rest: str) -> NormattivaLink:
        day: date | None = None

        m = _DATE_TEXT.search(rest)
        if m and m.group(2) in _MONTHS:
            day = _make_date(atto, int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
        else:
            m = _DATE_NUM.search(rest)
            if m:
                day = _make_date(atto, int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if m and day is not None:
            rest = f"{rest[: m.start()]} {rest[m.end() :]}"

        if day is not None:
            year = day.year
            nm = _NUM_LABELLED.search(rest) or _NUM_BARE.search(rest)
            if not nm:
                raise ValueError(_errore(atto))
            number = int(nm.group(1))
        else:
            ym = _NUM_YEAR.search(rest)
            if not ym:
                raise ValueError(_errore(atto))
            number, year = int(ym.group(1)), int(ym.group(2))

        if number < 1 or not MIN_YEAR <= year <= MAX_YEAR:
            raise ValueError(_errore(atto))

        if day is not None:
            when = day.isoformat()
            citazione = f"{label} {day.day} {_month_name(day.month)} {day.year}, n. {number}"
            nota = NOTA_UFFICIALITA
        else:
            when = str(year)
            citazione = f"{label} n. {number} del {year}"
            nota = (
                "La data esatta non e' stata indicata: il link usa la forma abbreviata "
                "anno;numero, accettata da Normattiva. " + NOTA_UFFICIALITA
            )
        urn = f"urn:nir:stato:{urn_type}:{when};{number}"
        return NormattivaLink(
            atto=citazione, urn=urn, link=f"{self._base}/uri-res/N2Ls?{urn}", nota=nota
        )


def _make_date(atto: str, year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError:
        raise ValueError(_errore(atto)) from None


def _month_name(month: int) -> str:
    return next(name for name, i in _MONTHS.items() if i == month)


def _errore(atto: str) -> str:
    return (
        f"Non riesco a interpretare l'atto '{atto}'. Indica tipo e estremi, ad esempio "
        "'legge 5 agosto 2026, n. 140', 'DL 144/2026' o 'DPR 26 ottobre 1972 n. 633'."
    )
