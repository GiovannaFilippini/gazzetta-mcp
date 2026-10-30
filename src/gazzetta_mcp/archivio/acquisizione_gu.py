"""Ingestion of the Gazzetta Ufficiale into the archive (step 2, decision 090).

Only talks to a ``SourceClient`` and a ``Parser`` (rate limit and user-agent live in the client)
and writes to the ``ArchiveStore``. All the progress is kept in the store, so every job can be
stopped and started again: acts already archived are never downloaded twice.

Series without a known act text URL (``ATTO_URL_SEGMENT`` is None: S2, S5, P2) are archived from
the issue summary alone: title, issuer, kind and link, with an empty text. The text is never
invented, and since an archived act is immutable it cannot be added later without a new store
method.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone

from ..interfaces import Parser, SourceClient
from ..models import ATTO_URL_SEGMENT, Atto, Serie, SommarioVoce
from ..parsing import ParseError
from ..sources.gu import GuError, GuHttpError, resolve_numero, sommario_matches
from .store import ArchiveStore
from .tipi import NumeroDaFare

log = logging.getLogger(__name__)

BASE_URL = "https://www.gazzettaufficiale.it"
BACKOFF_BASE_SECONDS = 30.0
BACKOFF_CAP_SECONDS = 15 * 60.0

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
) -> int:
    """Archive the acts of one issue. Returns how many acts were new.

    Costs one request for the summary plus about three per act that is not archived yet.
    The issue is marked 'fatto' (or 'vuoto' if it has no acts); 'errore' with the message when
    the number is wrong, a page cannot be read or an act has no text. An act that fails does not
    stop the others. A network or HTTP problem (``GuHttpError``) is different: it says nothing
    about the issue, so the issue goes back to 'da_fare' (the attempt is not counted, the message
    is kept) and the error is raised for the caller to back off. Acts saved so far stay saved.
    """
    try:
        return await _acquisisci(client, parser, store, voce, base_url)
    except GuHttpError as exc:
        store.segna_numero(voce.serie, voce.data, "da_fare", str(exc))
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
    for v in sommario.voci:
        if store.has_atto(v.codice):
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
        nuovi += store.put_atto(atto, fonte="gu")

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
    the latest issue is known, from the RSS feed. Network errors are raised to the caller.
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

    On a network or HTTP problem (429, 5xx, timeouts...) it waits with an exponential back-off
    (``backoff_base * 2**n``, capped at ``backoff_tetto``) and retries the same issue up to
    ``tentativi_rete`` times in a row, then stops for good instead of insisting; the issue stays
    in the queue. Problems inside an issue (a bad page) are recorded on it and the run goes on.
    """
    elaborati = nuovi = 0
    attesa = 0.0
    for voce in store.prossimi_numeri(serie, max_numeri):
        for tentativo in range(tentativi_rete + 1):
            try:
                nuovi += await acquisisci_numero(client, parser, store, voce, base_url=base_url)
                elaborati += 1
                break
            except GuHttpError as exc:
                if tentativo == tentativi_rete:
                    log.warning("Recovery of %s stopped: %s", serie.value, exc)
                    store.set_stato(f"gu.{serie.value}.ultimo_stop", f"{voce.data}: {exc}")
                    return EsitoRecupero(elaborati, nuovi, True, str(exc), attesa)
                pausa = attesa_backoff(tentativo, backoff_base, backoff_tetto)
                attesa += pausa
                await sleep(pausa)
    return EsitoRecupero(elaborati, nuovi, False, None, attesa)
