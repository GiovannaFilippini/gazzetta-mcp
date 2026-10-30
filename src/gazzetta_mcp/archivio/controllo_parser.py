"""Daily check that the parser still understands the pages of the GU (decision 090).

The site may change its pages without notice. The check downloads a handful of sample pages
(one issue summary per sample and, for the series that have act pages, the first act of that
summary), runs the parser on them and verifies that the expected fields are still extracted.
It never notifies anybody: it returns a report with an ``ok`` flag and a readable text for the
cron, and stores the outcome in the archive under the key ``controllo_parser``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone

from ..config import Settings
from ..interfaces import Parser, SourceClient
from ..models import ATTO_URL_SEGMENT, Serie, SommarioVoce
from .store import ArchiveStore

CHIAVE_STATO = "controllo_parser"


@dataclass(frozen=True)
class Campione:
    """One issue to sample: its summary is fetched, and so is its first act when possible."""

    serie: Serie
    data: date
    numero: int


@dataclass
class EsitoCampione:
    serie: str
    data: str
    numero: int
    voci: int = 0  # entries found in the summary
    codice_atto: str | None = None  # act sampled, if any
    richieste: int = 0  # calls made to the client for this sample
    problemi: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problemi


@dataclass
class RapportoControllo:
    controllato_il: str
    esiti: list[EsitoCampione]
    numeri_vuoti: list[str]  # "SG 2026-10-03 n. 230": samples whose summary has no entries
    numeri_archivio: dict[str, int] = field(default_factory=dict)  # queue states, informational

    @property
    def ok(self) -> bool:
        return bool(self.esiti) and all(e.ok for e in self.esiti)

    @property
    def testo(self) -> str:
        """Readable summary for the cron log or an alert message."""
        righe = [f"Controllo parser GU del {self.controllato_il}: {'OK' if self.ok else 'FALLITO'}"]
        if not self.esiti:
            righe.append("- nessun campione controllato")
        for e in self.esiti:
            stato = "ok" if e.ok else "ERRORE"
            atto = f", atto {e.codice_atto}" if e.codice_atto else ""
            righe.append(f"- {e.serie} {e.data} n. {e.numero}: {stato} ({e.voci} voci{atto})")
            righe.extend(f"    {p}" for p in e.problemi)
        if self.numeri_vuoti:
            righe.append("Numeri vuoti: " + ", ".join(self.numeri_vuoti))
        return "\n".join(righe)

    def a_json(self) -> str:
        d = asdict(self)
        d["ok"] = self.ok
        for e, esito in zip(d["esiti"], self.esiti, strict=True):
            e["ok"] = esito.ok
        return json.dumps(d, ensure_ascii=False, sort_keys=True)


async def controlla_parser(
    client: SourceClient,
    parser: Parser,
    store: ArchiveStore,
    *,
    campioni: list[Campione],
    base_url: str | None = None,
) -> RapportoControllo:
    """Fetch the sample pages, check the parser output and record the outcome.

    Per sample: one request for the summary, which must have at least one entry, each with code,
    title and issuer. Then, once per series that has act pages (``ATTO_URL_SEGMENT``), the first
    entry of that summary is fetched as an act (the client needs the card and the text, so a few
    requests) and must have title, issuer and a non-empty text. Every request goes through the
    client, which owns the rate limiter. A failure of one sample never stops the others. The
    result is saved with ``store.set_stato('controllo_parser', <json>)``.
    """
    root = base_url or Settings().gu_base_url
    atto_gia_provato: set[Serie] = set()
    esiti: list[EsitoCampione] = []
    vuoti: list[str] = []
    for c in campioni:
        esito = EsitoCampione(serie=c.serie.value, data=c.data.isoformat(), numero=c.numero)
        esiti.append(esito)
        voci = await _controlla_sommario(client, parser, c, esito, root)
        if voci is None:
            continue
        if not voci:
            vuoti.append(f"{c.serie.value} {c.data.isoformat()} n. {c.numero}")
            continue
        if ATTO_URL_SEGMENT.get(c.serie) is None or c.serie in atto_gia_provato:
            continue
        atto_gia_provato.add(c.serie)
        await _controlla_atto(client, parser, c, voci[0], esito, root)
    rapporto = RapportoControllo(
        controllato_il=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        esiti=esiti,
        numeri_vuoti=vuoti,
        numeri_archivio=store.conteggio_numeri(),
    )
    store.set_stato(CHIAVE_STATO, rapporto.a_json())
    return rapporto


async def _controlla_sommario(
    client: SourceClient, parser: Parser, c: Campione, esito: EsitoCampione, root: str
) -> list[SommarioVoce] | None:
    """Entries of the summary, or None if the page could not be fetched or parsed."""
    esito.richieste += 1
    try:
        raw = await client.get_sommario(c.data, c.serie, c.numero)
        sommario = parser.parse_sommario(raw.content, c.serie, c.data, c.numero, root)
    except Exception as exc:  # noqa: BLE001 (any failure is a finding, not a crash)
        esito.problemi.append(f"sommario non leggibile: {type(exc).__name__}: {exc}")
        return None
    esito.voci = len(sommario.voci)
    if not sommario.voci:
        esito.problemi.append("numero vuoto: nessuna voce nel sommario")
        return []
    for v in sommario.voci:
        mancanti = [
            nome
            for nome, valore in (
                ("codice", v.codice),
                ("titolo", v.titolo),
                ("emettitore", v.emettitore),
            )
            if not valore or not valore.strip()
        ]
        if mancanti:
            esito.problemi.append(f"voce {v.codice or '?'} senza {', '.join(mancanti)}")
    return sommario.voci


async def _controlla_atto(
    client: SourceClient,
    parser: Parser,
    c: Campione,
    voce: SommarioVoce,
    esito: EsitoCampione,
    root: str,
) -> None:
    esito.codice_atto = voce.codice
    esito.richieste += 2
    try:
        scheda = await client.get_atto_scheda(voce.codice, c.data, c.serie)
        testo = await client.get_atto_testo(voce.codice, c.data, c.serie, voce.tipo)
        atto = parser.parse_atto(scheda.content, testo.content, voce.codice, c.serie, c.data, root)
    except Exception as exc:  # noqa: BLE001
        esito.problemi.append(f"atto {voce.codice} non leggibile: {type(exc).__name__}: {exc}")
        return
    for nome, valore in (
        ("titolo", atto.titolo),
        ("emettitore", atto.emettitore),
        ("testo", atto.testo),
    ):
        if not valore or not valore.strip():
            esito.problemi.append(f"atto {voce.codice}: {nome} vuoto")
