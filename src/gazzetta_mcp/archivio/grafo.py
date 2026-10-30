"""Graph of the relations between acts: extraction from the text of the GU and history queries.

Nodes are acts, edges are the typed ``Arco`` rows of the archive (decision 090). This module
produces the edges that the GU text tells us about (``fonte='gu'``: corrections and citations);
the edges that Normattiva provides (modifica, abroga, attua) are produced elsewhere.

Identity of the target act. The text of an act almost never gives the editorial code (e.g.
``26A05182``) of the act it refers to, only its type, date and number. We do NOT invent a code.
The target is named by a stable key, the Normattiva URN built with the rules of
``sources.normattiva`` (``urn:nir:stato:legge:1990-08-07;241``). The same key is stored in the
``urn`` column of ``atti`` when an archived act is known by it, and the queries below resolve
URN endpoints to archived codes through that column. Endpoints that cannot be resolved stay as
URNs: the history is then partial, never wrong.

Precision comes before coverage: when a reference is ambiguous (no number, no full date, plural
or regional types) no edge is produced.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from ..models import Atto
from ..sources.normattiva import NormattivaLinkBuilder
from .store import ArchiveStore
from .tipi import Arco

FONTE_GU = "gu"
MAX_CITAZIONI = 100  # per act: a safety net against pathological texts
PROFONDITA_MASSIMA = 20  # hard ceiling of the history queries
_HEAD_CHARS = 2000  # how much of the text is searched for the correction formulas
_LEAD_WINDOW = 400  # a correction formula must start within this many chars from the top

_LINKER = NormattivaLinkBuilder()

# -- recognising a citation ---------------------------------------------------------------

_TIPI = (
    r"legge\s+costituzionale|regio\s+decreto[\s-]+legislativo|regio\s+decreto[\s-]+legge"
    r"|regio\s+decreto|decreto[\s-]+legislativo|decreto[\s-]+legge"
    r"|decreto\s+del\s+presidente\s+della\s+repubblica"
    r"|decreto\s+del\s+presidente\s+del\s+consiglio\s+dei\s+ministri"
    r"|decreto\s+ministeriale|legge|d\.\s?lgs\.?|dlgs|d\.\s?l\.|d\.\s?p\.\s?r\.?|dpr"
    r"|d\.\s?p\.\s?c\.\s?m\.?|dpcm"
)
_MESI = (
    "gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre"
)
_DATA = rf"\d{{1,2}}\s?[°º]?\s+(?:{_MESI})\s+\d{{4}}"
_NUM = r"(?:n\.?|n°|nr\.?|numero)\s*\d{1,5}(?!\d)"
_START = r"(?<![A-Za-z\-])"
# Three accepted shapes, all complete (type + number + date or year):
#   A  legge 7 agosto 1990, n. 241
#   B  legge n. 241 del 7 agosto 1990
#   C  decreto-legge 144/2026   /   d.lgs. n. 50/2016
_CITAZIONE = (
    rf"{_START}(?:{_TIPI})\s+(?:"
    rf"{_DATA}\s*,?\s*{_NUM}"
    rf"|{_NUM}\s*(?:del|in\s+data|dell')\s*{_DATA}"
    rf"|(?:n\.?\s*)?\d{{1,5}}\s*/\s*\d{{4}}(?!\d)"
    r")"
)
_CITAZIONE_RE = re.compile(_CITAZIONE, re.IGNORECASE)
_INIZIO_RE = re.compile(rf"\s*(?:{_CITAZIONE})", re.IGNORECASE)

# -- recognising a correction -------------------------------------------------------------

_PREP = r"(?:all'|dell'|al|allo|alla|del|dello|della)\s*"
_LEAD = (
    r"(?P<lead>errata[\s-]*corrige|avviso\s+di\s+rettifica|comunicato\s+di\s+rettifica"
    r"|rettifiche|rettifica|comunicato)"
)
_CORREZIONE_RE = re.compile(
    rf"{_LEAD}[\s,:;\-]*(?:relativ[oa]\s+)?{_PREP}(?P<cit>{_CITAZIONE})", re.IGNORECASE
)
# Cues needed when the lead is a generic "comunicato": on its own it is not a correction.
_INDIZIO_ERRATA = re.compile(
    r"errata[\s-]*corrige|leggasi|si\s+legga|dove\s+e'\s+scritto|dove\s+è\s+scritto"
    r"|correzione|errore|errori",
    re.IGNORECASE,
)
_INDIZIO_RETTIFICA = re.compile(r"rettific", re.IGNORECASE)


def _normalizza(testo: str) -> str:
    return re.sub(r"\s+", " ", testo).strip()


_URN_PIENO_RE = re.compile(r"^urn:nir:stato:[^:]+:\d{4}-\d{2}-\d{2};\w+")
_URN_ATTO_RE = re.compile(r"^(urn:nir:stato:[^:]+:)(\d{4})(?:-\d{2}-\d{2})?;(.+)$")


def _chiave_atto(urn: str) -> tuple[str, str, str] | str:
    """Same act, whatever the form of its URN: (type, year, number); other strings as they are."""
    m = _URN_ATTO_RE.match(urn)
    return m.groups() if m else urn


def urn_da_citazione(citazione: str) -> str | None:
    """URN of a citation such as ``legge 7 agosto 1990, n. 241``, or None if not computable."""
    try:
        return _LINKER.link_for(citazione).urn or None
    except ValueError:
        return None


def urn_proprio(titolo: str) -> str | None:
    """URN of the act itself when its title starts with its own identification
    (``DECRETO LEGISLATIVO 18 aprile 2016, n. 50 - Codice dei contratti pubblici``)."""
    m = _INIZIO_RE.match(_normalizza(titolo))
    return urn_da_citazione(m.group(0).strip()) if m else None


def archi_correzione(codice: str, titolo: str, testo: str) -> list[Arco]:
    """Edge ``errata_corrige`` / ``rettifica`` from a correction notice to the corrected act.

    Recognised formulas, within the first lines: ``Errata corrige al/del <act>``,
    ``Avviso di rettifica ...``, ``Rettifica relativa al <act>`` and ``Comunicato relativo al
    <act>``. The generic "comunicato" counts only if the text also carries a correction cue
    ("leggasi", "dove e' scritto", "errata corrige", "rettifica", "correzione"): a plain
    communication about a decree is not a correction. The target must directly follow the
    formula and be a complete citation; the first match wins. Returns at most one edge.
    """
    testa = _normalizza(f"{titolo} {testo[:_HEAD_CHARS]}")
    m = _CORREZIONE_RE.search(testa)
    if m is None or m.start() > _LEAD_WINDOW:
        return []
    lead = re.sub(r"[\s-]+", " ", m.group("lead").lower())
    if lead.startswith("errata"):
        tipo = "errata_corrige"
    elif "rettific" in lead:
        tipo = "rettifica"
    elif _INDIZIO_ERRATA.search(testa):
        tipo = "errata_corrige"
    elif _INDIZIO_RETTIFICA.search(testa):
        tipo = "rettifica"
    else:
        return []
    urn = urn_da_citazione(m.group("cit"))
    if urn is None or urn == urn_proprio(titolo):
        return []
    return [Arco(da=codice, a=urn, tipo=tipo, fonte=FONTE_GU)]


def archi_citazioni(codice: str, testo: str, *, escludi: Iterable[str] = ()) -> list[Arco]:
    """Edges ``cita`` towards every act cited with a complete formula (type, date, number).

    ``escludi`` holds URNs to leave out (the act itself, the target of a correction). Edges are
    unique and keep the order of first appearance. Not extracted, on purpose: types the URN rules
    do not know (regional laws, EU acts), incomplete citations ("la legge n. 241 del 1990"),
    and the verbs around the citation (an "abrogato" is not guessed from prose).
    """
    saltare = {_chiave_atto(u) for u in escludi}
    trovati: list[str] = []
    for m in _CITAZIONE_RE.finditer(_normalizza(testo)):
        urn = urn_da_citazione(m.group(0))
        if urn:
            trovati.append(urn)
        if len(trovati) >= 4 * MAX_CITAZIONI:
            break
    # "decreto legislativo n. 165/2001" gives a year-only URN: when the same act is also cited
    # with its full date in this text, use the full one so the act is a single node.
    pieni = {_chiave_atto(u): u for u in trovati if _URN_PIENO_RE.match(u)}
    visti: dict[str, None] = {}
    for urn in trovati:
        urn = pieni.get(_chiave_atto(urn), urn)
        if _chiave_atto(urn) not in saltare:
            visti.setdefault(urn)
        if len(visti) >= MAX_CITAZIONI:
            break
    return [Arco(da=codice, a=urn, tipo="cita", fonte=FONTE_GU) for urn in visti]


def estrai_archi_testo(codice: str, titolo: str, testo: str) -> list[Arco]:
    """All the edges the text of one GU act tells us about (pure function)."""
    correzione = archi_correzione(codice, titolo, testo)
    escludi = {a.a for a in correzione}
    proprio = urn_proprio(titolo)
    if proprio:
        escludi.add(proprio)
    return correzione + archi_citazioni(codice, testo, escludi=escludi)


def estrai_archi_atto(atto: Atto) -> list[Arco]:
    """Edges (``fonte='gu'``) of an act: its correction target, if any, and its citations."""
    return estrai_archi_testo(atto.codice, atto.titolo, atto.testo)


def salva_archi_atti(store: ArchiveStore, atti: Iterable[Atto]) -> int:
    """Extract and store the edges of the acts. Returns how many edges were new.

    When the title of an archived act carries its own identification, its URN is recorded in
    the archive (only if no other act already owns it), so that edges pointing at that URN can
    be resolved to the act.
    """
    nuovi = 0
    for atto in atti:
        nuovi += store.put_archi(estrai_archi_atto(atto))
        urn = urn_proprio(atto.titolo)
        if urn and store.has_atto(atto.codice) and store.codice_da_urn(urn) is None:
            store.set_urn(atto.codice, urn)
    return nuovi


# -- history queries ----------------------------------------------------------------------

TIPI_STORICO = ("modifica", "abroga", "rettifica", "errata_corrige")
# Order of resolution: exact URN, then the year-only URN mapped by ``_mappa_brevi`` (passed to
# the query as the bound JSON of the CTE ``brevi``), then the endpoint as it is.
_CANON = (
    "COALESCE((SELECT codice FROM atti WHERE urn = archi.{col} LIMIT 1),"
    " (SELECT codice FROM brevi WHERE urn = archi.{col}), archi.{col})"
)
_URN_BREVE_RE = re.compile(r"^urn:nir:stato:([^:]+):(\d{4});(.+)$")


@dataclass(frozen=True)
class VoceStorico:
    codice: str  # code of the act, or its URN if the act is not archived
    profondita: int  # 1 = directly related to the starting act
    tipo: str  # relation by which the chain reaches it (one of TIPI_STORICO)
    direzione: str  # 'agisce_su' (it acts on the previous act) | 'subisce' (it is acted upon)


def storico(store: ArchiveStore, codice: str, *, profondita: int = 5) -> list[VoceStorico]:
    """Chain of acts that modify, repeal or correct the given one, and of those it modifies.

    Two separate walks over the edges of types ``modifica``, ``abroga``, ``rettifica``,
    ``errata_corrige`` (``cita`` and ``attua`` are not history): upwards (``direzione=
    'agisce_su'``: acts that act on the given one, then those that act on them) and downwards
    (``'subisce'``: acts acted upon by the given one, and so on). URN endpoints are resolved to
    archived codes. Cycles are cut (a path never visits an act twice) and ``profondita`` caps
    the length of the chains (at most ``PROFONDITA_MASSIMA``). An act reachable in several ways
    appears once per direction, with its shortest chain. The starting act is never included.
    Results are sorted by depth, then code.
    """
    if profondita < 1:
        return []
    cap = min(profondita, PROFONDITA_MASSIMA)
    brevi = _mappa_brevi(store)
    partenza = _risolvi(store, codice, brevi)
    risultato: list[VoceStorico] = []
    for direzione, da_col, a_col in (("agisce_su", "da", "a"), ("subisce", "a", "da")):
        # ``a_col`` is the column matched with the current node, ``da_col`` the one to move to.
        # Only constant fragments are interpolated; every value is a bound parameter.
        # MATERIALIZED lets SQLite index the small map: without it every edge scans it.
        materialized = "MATERIALIZED " if sqlite3.sqlite_version_info >= (3, 35, 0) else ""
        sql = f"""
            WITH RECURSIVE brevi(urn, codice) AS {materialized}(
                SELECT key, value FROM json_each(?)
            ),
            e(da, a, tipo) AS (
                SELECT {_CANON.format(col="da")}, {_CANON.format(col="a")}, tipo FROM archi
                WHERE tipo IN ({",".join("?" * len(TIPI_STORICO))})
            ),
            catena(nodo, prof, tipo, percorso) AS (
                SELECT e.{da_col}, 1, e.tipo, '|' || ? || '|' || e.{da_col} || '|'
                FROM e WHERE e.{a_col} = ? AND e.{da_col} <> ?
                UNION ALL
                SELECT e.{da_col}, c.prof + 1, e.tipo, c.percorso || e.{da_col} || '|'
                FROM e JOIN catena c ON e.{a_col} = c.nodo
                WHERE c.prof < ? AND instr(c.percorso, '|' || e.{da_col} || '|') = 0
            )
            SELECT nodo, MIN(prof) AS prof, tipo FROM catena GROUP BY nodo ORDER BY prof, nodo
        """  # the bare column ``tipo`` comes from the row holding the minimum depth
        params = [json.dumps(brevi), *TIPI_STORICO, partenza, partenza, partenza, cap]
        for r in store.read(sql, params):
            risultato.append(VoceStorico(r["nodo"], r["prof"], r["tipo"], direzione))
    risultato.sort(key=lambda v: (v.profondita, v.codice, v.direzione))
    return risultato


def _mappa_brevi(store: ArchiveStore) -> dict[str, str]:
    """Year-only URN endpoints of the edges -> the one archived act they stand for.

    A short URN resolves only when exactly one archived act has the same type, year and number;
    with none or several matches it is left out (never guess between acts).
    """
    rows = store.read(
        "SELECT a AS u FROM archi WHERE a GLOB 'urn:nir:stato:*;*'"
        " UNION SELECT da FROM archi WHERE da GLOB 'urn:nir:stato:*;*'"
    )
    mappa: dict[str, str] = {}
    for r in rows:
        m = _URN_BREVE_RE.match(r["u"])
        if m:
            codici = store.codici_da_urn_breve(*m.groups())
            if len(codici) == 1:
                mappa[r["u"]] = codici[0]
    return mappa


def _risolvi(store: ArchiveStore, chiave: str, brevi: dict[str, str]) -> str:
    """Canonical key of a node: the archived code if ``chiave`` is a known URN (full or short)."""
    if chiave in brevi:
        return store.codice_da_urn(chiave) or brevi[chiave]
    m = _URN_BREVE_RE.match(chiave)
    if m and not store.codice_da_urn(chiave):
        codici = store.codici_da_urn_breve(*m.groups())
        return codici[0] if len(codici) == 1 else chiave
    return store.codice_da_urn(chiave) or chiave
