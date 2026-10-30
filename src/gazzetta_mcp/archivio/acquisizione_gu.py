"""Ingestion of the Gazzetta Ufficiale into the archive (step 2, decision 090).

Only talks to a ``SourceClient`` and a ``Parser`` (rate limit and user-agent live in the client)
and writes to the ``ArchiveStore``. All the progress is kept in the store, so every job can be
stopped and started again: acts already archived are never downloaded twice.

Series without a known act text URL (``ATTO_URL_SEGMENT`` is None: S2, S5, P2) are archived from
the issue summary alone: title, issuer, kind and link, with an empty text. The text is never
invented: they are archived as partial (``completo=False``) so that they stay correctable.

Reaching further back than the last 30 days: ``accoda_indietro`` walks back from the oldest known
issue, one publication day at a time, with the numbers deduced and verified (see its docstring).
At the start of a year it finds the last number of the year before with ``ultimo_numero_anno``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone

from ..interfaces import Parser, SourceClient
from ..models import ATTO_URL_SEGMENT, Atto, Serie, SommarioVoce
from ..parsing import ParseError
from ..sources.gu import GuError, GuHttpError, GuNotFoundError, resolve_numero, sommario_matches
from .grafo import salva_archi_atti
from .store import ArchiveStore
from .tipi import NumeroDaFare

log = logging.getLogger(__name__)

BASE_URL = "https://www.gazzettaufficiale.it"
BACKOFF_BASE_SECONDS = 30.0
BACKOFF_CAP_SECONDS = 15 * 60.0

# Days of the week (Monday = 0) on which a series is published, when the weekly pattern is known.
# The issue number is progressive within the year; a day with no issue (holiday) has no number.
GIORNI_PUBBLICAZIONE: dict[Serie, frozenset[int]] = {
    Serie.SG: frozenset(range(6)),  # Monday to Saturday
    Serie.S4: frozenset({1, 4}),  # Tuesday and Friday
}
MAX_SALTI_CONSECUTIVI = 3  # unexpected days without issue in a row before giving up
MAX_SONDE_FINE_ANNO = 20  # requests allowed to find the last issue number of a year
MAX_GIORNI_FINE_ANNO = 4  # last publication days of December examined for that

Sleep = Callable[[float], Awaitable[None]]


def attesa_backoff(
    tentativo: int, base: float = BACKOFF_BASE_SECONDS, tetto: float = BACKOFF_CAP_SECONDS
) -> float:
    """Wait before retry number ``tentativo`` (0-based): ``base * 2**n``, never above ``tetto``."""
    return min(tetto, base * (2 ** max(0, tentativo)))


@dataclass(frozen=True)
class EsitoRecupero:
    numeri_elaborati: int  # issues processed in this run (any final state, errors included)
    atti_nuovi: int  # acts newly archived in this run
    fermato: bool  # True if the run stopped on a network / HTTP problem
    motivo: str | None  # the problem, when stopped
    attesa_totale: float  # seconds spent in back-off waits


async def acquisisci_numero(
    client: SourceClient,
    parser: Parser,
    store: ArchiveStore,
    voce: NumeroDaFare,
    *,
    base_url: str = BASE_URL,
    conta_tentativo: bool = True,
) -> int:
    """Archive the acts of one issue. Returns how many acts were new.

    Costs one request for the summary plus about three per act that is not archived yet.
    The issue is marked 'fatto' (or 'vuoto' if it has no acts); 'errore' with the message when
    the number is wrong, a page cannot be read or an act has no text. An act that fails does not
    stop the others. A network or HTTP problem (``GuHttpError``) is raised for the caller to
    back off, and the issue is marked 'errore' with the message: the attempt is counted, so an
    issue that keeps failing is dropped after ``max_tentativi`` instead of blocking the queue
    for good. With ``conta_tentativo=False`` (a retry inside one run) the issue goes back to
    'da_fare' without counting. Acts saved so far stay saved.

    An act archived with a partial or empty text (from Normattiva, or from the summary alone)
    is downloaded and replaced; an act with a full text is never downloaded again.
    """
    try:
        return await _acquisisci(client, parser, store, voce, base_url)
    except GuHttpError as exc:
        stato = "errore" if conta_tentativo else "da_fare"
        store.segna_numero(voce.serie, voce.data, stato, str(exc))
        raise


async def _acquisisci(
    client: SourceClient,
    parser: Parser,
    store: ArchiveStore,
    voce: NumeroDaFare,
    base_url: str,
) -> int:
    serie, giorno = voce.serie, voce.data
    numero = voce.numero
    try:
        if numero is None:
            # Slow and approximate (decision 010): works only for dates up to a year back.
            numero = await resolve_numero(client, giorno, serie)
            store.aggiungi_numeri([(serie, giorno, numero)])
        raw = await client.get_sommario(giorno, serie, numero)
        if not sommario_matches(raw.content, giorno, numero):
            store.segna_numero(
                serie, giorno, "errore", f"issue {numero} of {giorno} does not exist (stub page)"
            )
            return 0
        sommario = parser.parse_sommario(raw.content, serie, giorno, numero, base_url)
    except GuHttpError:
        raise
    except (GuError, ParseError) as exc:  # includes NumeroNotFoundError and GuNotFoundError
        store.segna_numero(serie, giorno, "errore", f"{type(exc).__name__}: {exc}")
        return 0

    if not sommario.voci:
        store.segna_numero(serie, giorno, "vuoto")
        return 0

    nuovi = 0
    problemi: list[str] = []
    senza_url = ATTO_URL_SEGMENT.get(serie) is None
    for v in sommario.voci:
        if store.has_atto(v.codice) if senza_url else store.ha_testo_completo(v.codice):
            continue
        try:
            atto = await _scarica_atto(client, parser, v, serie, giorno, numero, base_url)
        except GuHttpError:
            raise
        except (GuError, ParseError) as exc:
            problemi.append(f"{v.codice}: {type(exc).__name__}: {exc}")
            continue
        if atto is None:
            problemi.append(f"{v.codice}: empty text")
            continue
        completo = not senza_url
        if store.has_atto(v.codice):  # archived with a partial text: the GU copy completes it
            salvato = store.sostituisci_atto(atto, fonte="gu", completo=completo)
        else:
            salvato = store.put_atto(atto, fonte="gu", completo=completo)
            nuovi += salvato
        if salvato:
            salva_archi_atti(store, [atto])

    if problemi:
        extra = f" (+{len(problemi) - 5} more)" if len(problemi) > 5 else ""
        messaggio = f"{len(problemi)} acts not archived: " + "; ".join(problemi[:5]) + extra
        store.segna_numero(serie, giorno, "errore", messaggio)
    else:
        store.segna_numero(serie, giorno, "fatto")
    return nuovi


async def _scarica_atto(
    client: SourceClient,
    parser: Parser,
    v: SommarioVoce,
    serie: Serie,
    giorno: date,
    numero: int,
    base_url: str,
) -> Atto | None:
    """Download one act, or None if its text came out empty (it must not be archived: acts
    are immutable, an empty copy would hide the real one for good)."""
    adesso = datetime.now(timezone.utc)
    if ATTO_URL_SEGMENT.get(serie) is None:
        # No text URL known for this series: keep what the summary says, nothing more.
        return Atto(
            codice=v.codice,
            serie=serie,
            data=giorno,
            titolo=v.titolo,
            emettitore=v.emettitore,
            tipo=v.tipo,
            testo="",
            link=v.link,
            numero_gu=numero,
            scaricato_il=adesso,
        )
    scheda = await client.get_atto_scheda(v.codice, giorno, serie)
    # The text URL needs the kind of provision, which only the scheda tells.
    tipo = parser.parse_atto(scheda.content, b"", v.codice, serie, giorno, base_url).tipo
    testo = await client.get_atto_testo(v.codice, giorno, serie, tipo)
    atto = parser.parse_atto(scheda.content, testo.content, v.codice, serie, giorno, base_url)
    if not atto.testo.strip():
        return None
    # The scheda may miss the issue number; the summary knows it.
    return replace(atto, numero_gu=atto.numero_gu or numero, scaricato_il=adesso)


async def aggiorna_recenti(
    client: SourceClient,
    parser: Parser,
    store: ArchiveStore,
    serie: Serie,
) -> int:
    """Queue the issues of the last 30 days that the store does not know. Returns how many.

    Series with a "last 30 days" page give all their issues (one request); for the others only
    the latest issue is known, from the RSS feed, so any series can be queued. A network or
    HTTP problem (``GuHttpError``) is raised to the caller: that is the signal to stop the other
    GU series too. Nothing is queued in that case.
    """
    try:
        raw = await client.get_elenco_30giorni(serie)
        voci = [(serie, d, n) for d, n in parser.parse_elenco_30giorni(raw.content)]
    except GuHttpError:
        raise
    except GuError:  # UnsupportedSerieError, or no such page: fall back to the feed
        voci = []
    if not voci:
        feed = await client.get_feed(serie)
        ultimo = parser.parse_feed(feed.content, serie)
        voci = [(serie, ultimo.data, ultimo.numero)]
    return store.aggiungi_numeri(voci)


def _pasqua(anno: int) -> date:
    """Easter Sunday (Gauss' algorithm for the Gregorian calendar)."""
    a, b, c = anno % 19, anno // 100, anno % 100
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    mese, giorno = divmod(h + ell - 7 * m + 114, 31)
    return date(anno, mese, giorno + 1)


def _festivi(anno: int) -> set[date]:
    """Italian national holidays: the days on which the GU normally has no issue."""
    fissi = [(1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15), (11, 1), (12, 8), (12, 25), (12, 26)]
    return {date(anno, m, d) for m, d in fissi} | {_pasqua(anno) + timedelta(days=1)}


def _stima_numero(giorno: date, giorni: frozenset[int]) -> int:
    """Expected number of the issue of ``giorno``: publication days of the year up to it,
    holidays excluded. Only a guess to order the probes: every number is verified on the page."""
    festivi = _festivi(giorno.year)
    n = 0
    d = date(giorno.year, 1, 1)
    while d <= giorno:
        if d.weekday() in giorni and d not in festivi:
            n += 1
        d += timedelta(days=1)
    return n


async def ultimo_numero_anno(
    client: SourceClient,
    store: ArchiveStore,
    serie: Serie,
    anno: int,
    *,
    max_sonde: int = MAX_SONDE_FINE_ANNO,
) -> int | None:
    """Last issue number of ``anno`` for ``serie``, or None if it cannot be established.

    The numbering is progressive within the year, so the last number is the one of the last
    publication day. Starting from the end of December, the number of each day is guessed from
    the calendar (``_stima_numero``, tried with +-1) and verified on its summary page
    (``sommario_matches``: a page that does not match date and number is never accepted).
    The first day that matches is an anchor; the publication days after it are then probed with
    the next number, so a later issue (extra edition on the last days) is not missed. The
    answer is kept in ``gu.<SERIE>.ultimo_numero_<anno>`` and never searched twice. At most
    ``max_sonde`` requests; if no day can be verified within them the answer is None (never a
    guess). A ``GuHttpError`` is raised to the caller.
    """
    giorni = GIORNI_PUBBLICAZIONE.get(serie)
    if giorni is None:
        return None
    chiave = f"gu.{serie.value}.ultimo_numero_{anno}"
    noto = store.get_stato(chiave)
    if noto:
        return int(noto)

    provati: set[tuple[date, int]] = set()
    sonde = 0

    async def esiste(giorno: date, numero: int) -> bool | None:
        """True / False after a probe; None when the budget is over."""
        nonlocal sonde
        if numero < 1:
            return False
        if (giorno, numero) in provati:
            return False  # already seen not to match
        if sonde >= max_sonde:
            return None
        sonde += 1
        provati.add((giorno, numero))
        try:
            raw = await client.get_sommario(giorno, serie, numero)
        except GuNotFoundError:
            return False
        return sommario_matches(raw.content, giorno, numero)

    fine = date(anno, 12, 31)
    giorni_fine = [
        d for d in (fine - timedelta(days=i) for i in range(10)) if d.weekday() in giorni
    ][:MAX_GIORNI_FINE_ANNO]
    ancora: tuple[date, int] | None = None
    for giorno in giorni_fine:
        stima = _stima_numero(giorno, giorni)
        for numero in (stima, stima - 1, stima + 1):
            esito = await esiste(giorno, numero)
            if esito is None:
                return None
            if esito:
                ancora = (giorno, numero)
                break
        if ancora:
            break
    if ancora is None:
        return None
    ultimo_giorno, ultimo = ancora
    # Anything after the anchor, on any calendar day (an extra edition can come on a Sunday or a
    # holiday, or twice on the same day): keep asking for the next number until none exists.
    giorno = ultimo_giorno
    while giorno <= fine:
        esito = await esiste(giorno, ultimo + 1)
        if esito is None:
            return None  # cannot rule out a later issue: do not guess
        if esito:
            ultimo += 1
            continue  # the same day may carry one more
        giorno += timedelta(days=1)
    store.set_stato(chiave, str(ultimo))
    return ultimo


def _chiave_cursore(serie: Serie) -> str:
    return f"gu.{serie.value}.cursore_indietro"


async def accoda_indietro(
    client: SourceClient,
    parser: Parser,
    store: ArchiveStore,
    serie: Serie,
    *,
    quanti: int,
    max_salti: int = MAX_SALTI_CONSECUTIVI,
) -> int:
    """Queue up to ``quanti`` issues older than the oldest one known. Returns how many.

    The issue number cannot be computed from the date (decision 010), but within a year it is
    progressive: starting from the oldest known issue it is lowered by one for every earlier
    publication day (SG: Monday to Saturday; S4: Tuesday and Friday). Every day is verified with
    its summary page (``sommario_matches``; the GU answers 200 for any number): a day that does
    not match (holiday) is recorded as 'vuoto' without number and the count goes on from the
    same number. One request per day examined: at most ``quanti`` issues plus the holidays met.

    Limits: only SG and S4 have a known weekly pattern (the other series return 0: they can
    only be queued from the feed by ``aggiorna_recenti``); at the beginning of
    the year it takes the last number of the year before from ``ultimo_numero_anno`` (and stops,
    with the reason in ``ultimo_stop``, if that cannot be established with certainty); after
    ``max_salti`` unexpected days in a row it gives up (reason in ``gu.<SERIE>.ultimo_stop``)
    instead of searching without end, leaving those days unmarked. Progress is kept in
    ``gu.<SERIE>.cursore_indietro`` (the oldest day examined). A ``GuHttpError`` is raised to
    the caller; what was queued so far stays.
    """
    giorni = GIORNI_PUBBLICAZIONE.get(serie)
    if giorni is None or quanti <= 0:
        return 0
    righe = store.read(
        "SELECT data, numero FROM numeri WHERE serie = ? AND numero IS NOT NULL"
        " ORDER BY data LIMIT 1",
        (serie.value,),
    )
    if not righe:
        return 0  # nothing to start from: aggiorna_recenti gives the first issues
    ref_data = date.fromisoformat(righe[0]["data"])
    atteso = righe[0]["numero"] - 1
    cursore = store.get_stato(_chiave_cursore(serie))
    giorno = min(date.fromisoformat(cursore), ref_data) if cursore else ref_data

    accodati = 0
    anno = ref_data.year
    dubbi: list[date] = []  # days without a match: marked only if an earlier day matches
    while accodati < quanti:
        if atteso < 1:
            # The first issue of the year is queued: go on from the last of the year before.
            ultimo = await ultimo_numero_anno(client, store, serie, anno - 1)
            if ultimo is None:
                motivo = f"inizio anno {anno}: ultimo numero del {anno - 1} non determinabile"
                log.warning("Backward queue of %s stopped: %s", serie.value, motivo)
                store.set_stato(f"gu.{serie.value}.ultimo_stop", motivo)
                break
            anno -= 1
            atteso = ultimo
            giorno = date(anno + 1, 1, 1)
        giorno -= timedelta(days=1)
        if giorno.year != anno:
            motivo = f"inizio anno {anno}: numerazione incoerente, fascicolo {atteso} non trovato"
            log.warning("Backward queue of %s stopped: %s", serie.value, motivo)
            store.set_stato(f"gu.{serie.value}.ultimo_stop", motivo)
            break
        if giorno.weekday() not in giorni:
            continue
        try:
            raw = await client.get_sommario(giorno, serie, atteso)
            esiste = sommario_matches(raw.content, giorno, atteso)
        except GuNotFoundError:
            esiste = False
        if not esiste:
            dubbi.append(giorno)
            if len(dubbi) >= max_salti:
                motivo = f"{len(dubbi)} days in a row without issue, down to {dubbi[0]}"
                log.warning("Backward queue of %s stopped: %s", serie.value, motivo)
                store.set_stato(f"gu.{serie.value}.ultimo_stop", motivo)
                break
            continue
        for d in dubbi:  # a real issue comes before them: they were holidays
            store.aggiungi_numeri([(serie, d, None)])
            store.segna_numero(serie, d, "vuoto")
        dubbi.clear()
        accodati += store.aggiungi_numeri([(serie, giorno, atteso)])
        store.set_stato(_chiave_cursore(serie), giorno.isoformat())
        atteso -= 1
    return accodati


async def recupera_indietro(
    client: SourceClient,
    parser: Parser,
    store: ArchiveStore,
    serie: Serie,
    *,
    max_numeri: int,
    tentativi_rete: int = 3,
    backoff_base: float = BACKOFF_BASE_SECONDS,
    backoff_tetto: float = BACKOFF_CAP_SECONDS,
    sleep: Sleep = asyncio.sleep,
    base_url: str = BASE_URL,
) -> EsitoRecupero:
    """Archive up to ``max_numeri`` queued issues, newest first. Resumable: just call it again.

    When the queue is empty it first queues older issues with ``accoda_indietro``. On a network
    or HTTP problem (429, 5xx, timeouts...) it waits with an exponential back-off
    (``backoff_base * 2**n``, capped at ``backoff_tetto``) and retries the same step up to
    ``tentativi_rete`` times in a row, then stops for good instead of insisting: the result has
    ``fermato=True`` and the reason in ``motivo`` (the caller should stop the other GU series
    too). The attempt is counted once per run on the issue, so an issue that fails over and over
    is dropped after ``max_tentativi`` runs. Problems inside an issue (a bad page) are recorded
    on it and the run goes on.
    """
    elaborati = nuovi = 0
    attesa = 0.0

    def ferma(riferimento: str, exc: GuHttpError) -> EsitoRecupero:
        log.warning("Recovery of %s stopped: %s", serie.value, exc)
        store.set_stato(f"gu.{serie.value}.ultimo_stop", f"{riferimento}: {exc}")
        return EsitoRecupero(elaborati, nuovi, True, str(exc), attesa)

    voci = store.prossimi_numeri(serie, max_numeri)
    if not voci:
        for tentativo in range(tentativi_rete + 1):
            try:
                await accoda_indietro(client, parser, store, serie, quanti=max_numeri)
                break
            except GuHttpError as exc:
                if tentativo == tentativi_rete:
                    return ferma("queue", exc)
                pausa = attesa_backoff(tentativo, backoff_base, backoff_tetto)
                attesa += pausa
                await sleep(pausa)
        voci = store.prossimi_numeri(serie, max_numeri)
    for voce in voci:
        for tentativo in range(tentativi_rete + 1):
            ultimo = tentativo == tentativi_rete
            try:
                nuovi += await acquisisci_numero(
                    client, parser, store, voce, base_url=base_url, conta_tentativo=ultimo
                )
                elaborati += 1
                break
            except GuHttpError as exc:
                if ultimo:
                    return ferma(str(voce.data), exc)
                pausa = attesa_backoff(tentativo, backoff_base, backoff_tetto)
                attesa += pausa
                await sleep(pausa)
    return EsitoRecupero(elaborati, nuovi, False, None, attesa)
