"""Fill on request for the remote archive service (decision 090, step 2).

OFF by default (``--riempi``). When a reader asks for an act that is not archived, the service
takes it from the Gazzetta Ufficiale, archives it and returns it. This is the only path by which
the public service writes, so it is built to be as narrow as possible:

* reads stay on the read-only connection; writing uses a second ``ArchiveStore`` owned here;
* only valid codes of the allowed series, never a removed code (checked before any request);
* ONE shared ``SourceClient`` (so one rate limiter, 1 request/second), one job at a time, a
  bounded queue (full: "try again soon", no request), requests for the same code are merged;
* a per-IP and a global hourly cap on fills, separate from the read limit;
* finding the date of an act uses the existing ``GazzettaService`` logic (code letter, latest
  feeds) with a hard budget of ``MAX_RICHIESTE`` requests per act, never a scan;
* an act with an empty text is not saved; a network error writes nothing, and repeated 429/5xx
  open a circuit breaker with the same back-off as ``acquisizione_gu``;
* the text is saved and its links extracted by the same functions as the scheduled ingestion.

The code that was asked for is never logged.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date

from ..cache.sqlite import SqliteCache
from ..config import Settings
from ..interfaces import Parser, SourceClient
from ..models import ATTO_URL_SEGMENT, Atto, RawPage, Serie, SommarioVoce
from ..parsing import ParseError
from ..service import GazzettaService
from ..sources.gu import GuError, GuHttpError, GuNotFoundError
from ..sources.normattiva import NormattivaLinkBuilder
from .acquisizione_gu import BASE_URL, _scarica_atto, attesa_backoff
from .grafo import salva_archi_atti
from .remoto import TokenBucket
from .store import ArchiveStore

log = logging.getLogger("gazzetta_mcp.riempimento")

CODICE_VALIDO = re.compile(r"^[0-9A-Z]{6,14}$")
MAX_RICHIESTE = 4  # requests to the source per act, date lookup included
MAX_CODA = 20  # acts waiting or being filled
PER_IP_ORA = 5
GLOBALE_ORA = 60
ERRORI_PER_APRIRE = 3  # consecutive network / HTTP failures before the breaker opens
TIMEOUT_LAVORO = 90.0  # seconds for one act
TIMEOUT_ATTESA = 150.0  # seconds a caller waits for its act
PRIMO_ANNO = 1946

OK = "ok"
NON_TROVATO = "non_trovato"
RIPROVA = "riprova"
LIMITE = "limite"

MSG_RIPROVA = (
    "Il servizio sta gia' recuperando altri atti dalla Gazzetta Ufficiale, oppure la fonte non "
    "risponde: riprova tra poco."
)
MSG_LIMITE_IP = (
    "Hai raggiunto il limite di atti nuovi che questo servizio recupera per te in un'ora "
    "({n}): riprova piu' tardi, oppure leggi l'atto dal sito ufficiale della Gazzetta Ufficiale."
)
MSG_LIMITE_GLOBALE = (
    "Il servizio ha raggiunto il limite orario di atti nuovi recuperati dalla Gazzetta "
    "Ufficiale: riprova tra un'ora, oppure leggi l'atto dal sito ufficiale."
)


@dataclass(frozen=True)
class Esito:
    stato: str  # OK, NON_TROVATO, RIPROVA or LIMITE
    messaggio: str = ""


class _ClienteContato:
    """Wraps the source client: counts requests (hard budget) and notes network problems.

    ``GazzettaService._lookup_date`` swallows source errors; the flag lets the filler still
    tell "not found" from "the source is failing". Jobs run one at a time, so one instance
    is enough: ``nuovo_lavoro`` resets it.
    """

    def __init__(self, client: SourceClient, massimo: int) -> None:
        self._client = client
        self._massimo = massimo
        self.richieste = 0
        self.errore_http = False
        self._schede: dict[tuple[str, date, Serie], RawPage] = {}

    def nuovo_lavoro(self) -> None:
        self.richieste = 0
        self.errore_http = False
        self._schede = {}

    async def _conta(self, coro_fn: Callable[[], object]) -> RawPage:
        if self.richieste >= self._massimo:
            raise GuError("request budget for one act exhausted")
        self.richieste += 1
        try:
            return await coro_fn()  # type: ignore[no-any-return,misc]
        except GuHttpError:
            self.errore_http = True
            raise

    async def get_feed(self, serie: Serie) -> RawPage:
        return await self._conta(lambda: self._client.get_feed(serie))

    async def get_atto_scheda(self, codice: str, data: date, serie: Serie) -> RawPage:
        chiave = (codice, data, serie)
        if chiave not in self._schede:  # asked twice in one job (check, then download): once
            self._schede[chiave] = await self._conta(
                lambda: self._client.get_atto_scheda(codice, data, serie)
            )
        return self._schede[chiave]

    async def get_atto_testo(
        self, codice: str, data: date, serie: Serie, tipo: str | None
    ) -> RawPage:
        return await self._conta(lambda: self._client.get_atto_testo(codice, data, serie, tipo))

    def __getattr__(self, name: str):  # url_* helpers: no network
        if name.startswith("url_"):
            return getattr(self._client, name)
        raise AttributeError(name)


class Riempitore:
    """Fills the archive with one act on request. See the module docstring."""

    def __init__(
        self,
        client: SourceClient,
        parser: Parser,
        scrittore: ArchiveStore,
        serie_consentite: Sequence[Serie],
        *,
        per_ip_ora: int = PER_IP_ORA,
        globale_ora: int = GLOBALE_ORA,
        max_coda: int = MAX_CODA,
        settings: Settings | None = None,
        clock: Callable[[], float] = time.monotonic,
        oggi: Callable[[], date] = date.today,
        timeout_lavoro: float = TIMEOUT_LAVORO,
        timeout_attesa: float = TIMEOUT_ATTESA,
    ) -> None:
        if not serie_consentite:
            raise ValueError("indica almeno una serie consentita")
        if per_ip_ora < 1 or globale_ora < 1 or max_coda < 1:
            raise ValueError("i limiti del riempimento devono essere almeno 1")
        settings = settings or Settings()
        self._client = _ClienteContato(client, MAX_RICHIESTE)
        self._parser = parser
        self._scrittore = scrittore
        self._consentite = frozenset(serie_consentite)
        self._per_ip_ora = per_ip_ora
        self._base = settings.gu_base_url.rstrip("/") or BASE_URL
        self._clock = clock
        self._oggi = oggi
        self._max_coda = max_coda
        self._timeout_lavoro = timeout_lavoro
        self._timeout_attesa = timeout_attesa
        # Caps on fills, apart from the read limit: tokens refill evenly over the hour.
        self._bucket_ip = TokenBucket(per_ip_ora / 60.0, per_ip_ora, clock=clock)
        self._bucket_globale = TokenBucket(globale_ora / 60.0, globale_ora, clock=clock)
        # Date lookup reuses the service logic (code letter, latest feeds); the in-memory cache
        # only keeps the feeds, so the next lookups cost nothing.
        self._cache = SqliteCache(":memory:")
        self._servizio = GazzettaService(
            self._client,  # type: ignore[arg-type]
            parser,
            self._cache,
            NormattivaLinkBuilder(settings),
            settings,
        )
        self._lock = asyncio.Lock()  # one job at a time
        self._in_corso: dict[str, asyncio.Task[Esito]] = {}
        self._errori = 0  # consecutive network / HTTP failures
        self._aperture = 0  # times the breaker opened in a row
        self._aperto_fino = 0.0

    async def aclose(self) -> None:
        for task in list(self._in_corso.values()):
            task.cancel()
        self._cache.close()
        self._scrittore.close()
        chiudi = getattr(self._client._client, "aclose", None)
        if chiudi is not None:
            await chiudi()

    # -- entry point ----------------------------------------------------------------------

    async def riempi(
        self,
        codice: str,
        *,
        ip: str,
        serie: Serie | None = None,
        data: date | None = None,
    ) -> Esito:
        """Archive the act if it can be got from the source. ``OK`` means it is now archived."""
        if not CODICE_VALIDO.match(codice) or self._scrittore.e_rimosso(codice):
            return Esito(NON_TROVATO)
        if serie is not None and serie not in self._consentite:
            return Esito(NON_TROVATO)
        if data is not None and not PRIMO_ANNO <= data.year <= self._oggi().year:
            return Esito(NON_TROVATO)
        task = self._in_corso.get(codice)
        if task is None:
            if self._clock() < self._aperto_fino or len(self._in_corso) >= self._max_coda:
                return Esito(RIPROVA, MSG_RIPROVA)
            if not self._bucket_ip.allow(ip)[0]:
                return Esito(LIMITE, MSG_LIMITE_IP.format(n=self._per_ip_ora))
            if not self._bucket_globale.allow("*")[0]:
                return Esito(LIMITE, MSG_LIMITE_GLOBALE)
            task = asyncio.get_running_loop().create_task(self._lavora(codice, serie, data, ip))
            self._in_corso[codice] = task
            task.add_done_callback(lambda _t, c=codice: self._in_corso.pop(c, None))
        # Whoever else asks for the same code just waits for this job: one request to the source.
        try:
            return await asyncio.wait_for(asyncio.shield(task), self._timeout_attesa)
        except asyncio.TimeoutError:
            return Esito(RIPROVA, MSG_RIPROVA)

    # -- the job --------------------------------------------------------------------------

    async def _lavora(self, codice: str, serie: Serie | None, data: date | None, ip: str) -> Esito:
        async with self._lock:
            if self._clock() < self._aperto_fino:  # the breaker opened while we were queued
                return Esito(RIPROVA, MSG_RIPROVA)
            self._client.nuovo_lavoro()
            try:
                esito = await asyncio.wait_for(
                    self._scarica(codice, serie, data), self._timeout_lavoro
                )
            except asyncio.TimeoutError:
                self._client.errore_http = True
                esito = Esito(RIPROVA, MSG_RIPROVA)
            except GuHttpError:  # already noted by the client wrapper
                esito = Esito(RIPROVA, MSG_RIPROVA)
            except Exception as exc:  # noqa: BLE001  (a job must not break the service)
                log.warning("Fill on request failed: %s", type(exc).__name__)
                esito = Esito(RIPROVA, MSG_RIPROVA)
            if self._client.errore_http:
                self._registra_errore()
                if esito.stato != OK:
                    return Esito(RIPROVA, MSG_RIPROVA)
            else:
                self._errori = self._aperture = 0
            if esito.stato == NON_TROVATO and self._client.richieste == 0:
                # Answered without asking the source: it cost nothing, so it must not burn the
                # hourly caps (otherwise made-up codes would exhaust them for everyone).
                self._bucket_ip.rimborsa(ip)
                self._bucket_globale.rimborsa("*")
            return esito

    def _registra_errore(self) -> None:
        self._errori += 1
        if self._errori >= ERRORI_PER_APRIRE:
            pausa = attesa_backoff(self._aperture)
            self._aperto_fino = self._clock() + pausa
            self._aperture += 1
            self._errori = 0
            log.warning("Source failing: fill on request paused for %.0f s", pausa)

    async def _scarica(self, codice: str, serie: Serie | None, data: date | None) -> Esito:
        if self._scrittore.e_rimosso(codice):
            return Esito(NON_TROVATO)
        if self._scrittore.ha_testo_completo(codice):
            return Esito(OK)  # archived meanwhile (by a scheduled job): nothing to fetch
        s, d, indovinata = self._servizio._locate(codice, serie, data)
        if not indovinata and s not in self._consentite:
            return Esito(NON_TROVATO)  # before any request
        if indovinata and not self._consentite & {Serie.SG, Serie.S4}:
            return Esito(NON_TROVATO)
        if d is None:
            trovata = await self._servizio._lookup_date(codice, serie, s, indovinata)
            if trovata is None:
                return Esito(NON_TROVATO)
            s, d = trovata
        if s not in self._consentite or ATTO_URL_SEGMENT.get(s) is None:
            return Esito(NON_TROVATO)  # never archived: not served, or no known text URL
        try:
            # The site answers 200 with a generic page for a code or date that does not exist, and
            # then fails on the following pages: look at the title first, so a wrong code is
            # "not found" and never counts as a failure of the source.
            scheda = await self._client.get_atto_scheda(codice, d, s)
            vuota = self._parser.parse_atto(scheda.content, b"", codice, s, d, self._base)
            if not vuota.titolo.strip():
                return Esito(NON_TROVATO)
            atto = await _scarica_atto(
                self._client,  # type: ignore[arg-type]
                self._parser,
                SommarioVoce(codice, "", "", "", ""),
                s,
                d,
                0,  # the issue number is not known: the scheda may carry it, else none
                self._base,
            )
        except GuHttpError:
            raise
        except (GuNotFoundError, GuError, ParseError):
            return Esito(NON_TROVATO)
        if atto is None or not atto.titolo.strip():  # empty or partial: never saved
            return Esito(NON_TROVATO)
        atto = replace(atto, numero_gu=atto.numero_gu or None)
        # Writing waits for SQLite if a scheduled job holds the file: do it off the event loop.
        return await asyncio.to_thread(self._salva, codice, atto)

    def _salva(self, codice: str, atto: Atto) -> Esito:
        # Same steps as the scheduled ingestion: one transaction for the act, then its links.
        if self._scrittore.has_atto(codice):
            salvato = self._scrittore.sostituisci_atto(atto, fonte="gu", completo=True)
        else:
            salvato = self._scrittore.put_atto(atto, fonte="gu", completo=True)
        if not salvato:
            return Esito(NON_TROVATO)
        try:
            salva_archi_atti(self._scrittore, [atto])
        except sqlite3.Error:  # the act is saved; its links will come with the next update
            log.warning("Links of a filled act not saved")
        return Esito(OK)
