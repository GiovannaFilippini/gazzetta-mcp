"""Business logic of the MCP server. The tools in ``tools/`` are thin wrappers around this.

Every public method returns a JSON-serialisable dict that always carries ``fonte`` (official
links) and ``avvertenza`` (the disclaimer). Failures raise :class:`ServiceError` with a short
Italian message; use :func:`user_message` to turn any exception into such a message.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .cache.sqlite import CacheError, SqliteCache
from .concorsi import BANDI, classify, estrai_posti, keyword_matcher
from .config import Settings
from .interfaces import ArchiveSearch, Cache, NormattivaLinker, Parser, SourceClient
from .models import DISCLAIMER, Atto, SearchFilters, SearchHit, Serie, Sommario
from .parsing import GuParser, ParseError
from .regioni import normalize, normalizza_regione, regione_ente
from .searchtext import count_matches, word_groups
from .sources.archivio import ArchivioClient
from .sources.gu import (
    GuClient,
    GuError,
    GuHttpError,
    GuNotFoundError,
    NumeroNotFoundError,
    UnsupportedSerieError,
    resolve_numero,
    sommario_matches,
)
from .sources.normattiva import NormattivaLinkBuilder
from .sources.ratelimit import RateLimiter
from .sources.ricerca_gu import RicercaGuClient

# Feeds that are already cached are used for date lookups whatever their age.
_ANY_AGE = 10**9
_CODICE = re.compile(r"^[0-9A-Z]{6,14}$")
# Editorial code letter -> series, only where the letter is unambiguous (docs/fonti.md).
_LETTER_TO_SERIE = {"A": Serie.SG, "G": Serie.SG, "E": Serie.S4}


class ServiceError(Exception):
    """A problem the user can understand and act on. The message is in Italian."""


def user_message(exc: BaseException) -> str:
    """Short Italian message for any expected error; never a traceback."""
    if isinstance(exc, ServiceError):
        return str(exc)
    if isinstance(exc, NumeroNotFoundError):
        return (
            "Non trovo un numero della Gazzetta per quella data e serie (forse quel giorno non "
            "e' uscito nulla, o la data e' nel futuro). Prova con un'altra data oppure chiedi "
            "prima le ultime pubblicazioni con ultime_pubblicazioni."
        )
    if isinstance(exc, GuNotFoundError):
        return (
            "Non ho trovato quella pagina sul sito della Gazzetta Ufficiale. Controlla di aver "
            "copiato bene il codice, oppure cerca l'atto per parole chiave con cerca o "
            "ultime_pubblicazioni."
        )
    if isinstance(exc, UnsupportedSerieError):
        return (
            "Il testo degli atti di questa serie non si puo' ancora leggere da qui: apri il "
            "link ufficiale che trovi nel risultato per leggerlo sul sito."
        )
    if isinstance(exc, GuHttpError):
        return (
            "Il sito della Gazzetta Ufficiale non risponde o ha dato un errore. Riprova tra "
            "qualche minuto; se continua, controlla la connessione a Internet "
            "(da terminale: gazzetta-mcp --prova)."
        )
    if isinstance(exc, GuError):
        return (
            "Non sono riuscito a contattare la Gazzetta Ufficiale. Controlla la connessione a "
            "Internet e riprova tra qualche minuto."
        )
    if isinstance(exc, ParseError):
        return (
            "La pagina ricevuta dalla Gazzetta Ufficiale ha un formato che non riconosco, "
            "quindi non l'ho potuta leggere. Apri il link ufficiale del risultato per "
            "consultarla direttamente sul sito."
        )
    if isinstance(exc, CacheError):
        return (
            f"Problema con la memoria locale dei risultati (cache): {exc} "
            "Da terminale puoi verificare con gazzetta-mcp --prova."
        )
    if isinstance(exc, ValueError):
        return str(exc)
    return (
        "Errore interno imprevisto. Riprova; se si ripete, prova con parole chiave diverse "
        "o apri il sito ufficiale della Gazzetta Ufficiale."
    )


@dataclass(frozen=True)
class Limits:
    max_chars: int = 20000  # characters of act text per call
    max_feed_items: int = 50
    max_sommario_voci: int = 300
    concorsi_results: int = 30
    max_search_results: int = 100
    # Issues whose table of contents is loaded automatically by cerca / cerca_concorsi.
    recent_issues_s4: int = 9
    recent_issues_sg: int = 24  # about 30 days of the Serie Generale
    max_recent_issues: int = 30  # hard cap of network fetches of issues per call
    year_days: int = 365  # target of periodo='anno'
    older_block: int = 24  # older issues loaded per call with periodo='anno'
    concorsi_window_days: int = 30  # a call is considered open this long after publication


def _parse_serie(value: str | Serie | None, default: Serie | None = None) -> Serie | None:
    if value is None or value == "":
        return default
    if isinstance(value, Serie):
        return value
    try:
        return Serie(value.strip().upper())
    except ValueError:
        valide = ", ".join(s.value for s in Serie)
        raise ServiceError(
            f"La serie '{value}' non esiste. Valori ammessi: {valide}. "
            "Se non sai quale usare, ometti il parametro: di solito basta SG (Serie Generale)."
        ) from None


def _parse_date(value: str | date | None, nome: str = "data") -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ServiceError(
            f"Non capisco la data '{nome}': scrivila nel formato AAAA-MM-GG, "
            "ad esempio 2026-10-03 per il 3 ottobre 2026."
        ) from None


def _short(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


class GazzettaService:
    """Orchestrates source client, parser, cache and Normattiva linker."""

    def __init__(
        self,
        client: SourceClient,
        parser: Parser,
        cache: Cache,
        linker: NormattivaLinker,
        settings: Settings | None = None,
        limits: Limits | None = None,
        today: Callable[[], date] = date.today,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        closers: tuple[Callable[[], Any], ...] = (),
        archivio: ArchiveSearch | None = None,
        ricerca_gu: ArchiveSearch | None = None,
        normattiva_limiter: RateLimiter | None = None,
    ) -> None:
        self._client = client
        self._parser = parser
        self._cache = cache
        self._linker = linker
        self._settings = settings or Settings()
        self._limits = limits or Limits()
        self._today = today
        self._now = now
        self._closers = closers
        self._archivio = archivio
        self._ricerca_gu = ricerca_gu
        # One limiter for the whole Normattiva site, shared by every client that calls it.
        self._normattiva_limiter = normattiva_limiter or RateLimiter(
            self._settings.requests_per_second
        )
        self._base = self._settings.gu_base_url.rstrip("/")

    async def aclose(self) -> None:
        """Release network and database resources (idempotent enough for shutdown)."""
        for closer in self._closers:
            result = closer()
            if hasattr(result, "__await__"):
                await result

    # --- helpers --------------------------------------------------------------------

    def _result(self, data: dict[str, Any], fonte: list[str]) -> dict[str, Any]:
        out = dict(data)
        out["fonte"] = [f for f in dict.fromkeys(fonte) if f] or [self._base]
        out["avvertenza"] = DISCLAIMER
        return out

    async def _feed(self, serie: Serie):
        cached = self._cache.get_feed(serie, self._settings.cache_ttl_feed_seconds)
        if cached is not None:
            return cached, True
        raw = await self._client.get_feed(serie)
        feed = self._parser.parse_feed(raw.content, serie)
        self._cache.put_feed(feed)
        return feed, False

    # --- 1. ultime_pubblicazioni ----------------------------------------------------

    async def ultime_pubblicazioni(self, serie: str = "SG", giorni: int = 7) -> dict[str, Any]:
        s = _parse_serie(serie, Serie.SG)
        if giorni < 1 or giorni > 90:
            raise ServiceError(
                "Il numero di giorni deve essere tra 1 e 90: riprova con un valore in questo intervallo."
            )
        feed, from_cache = await self._feed(s)
        since = self._today() - timedelta(days=giorni)
        items = [i for i in feed.items if i.data >= since]
        shown = items[: self._limits.max_feed_items]
        return self._result(
            {
                "serie": s.value,
                "giorni": giorni,
                "ultimo_numero": feed.numero,
                "data_ultimo_numero": feed.data.isoformat(),
                "totale": len(items),
                "mostrati": len(shown),
                "troncato": len(items) > len(shown),
                "dalla_cache": from_cache,
                "nota": (
                    "Il feed ufficiale contiene solo le pubblicazioni piu' recenti: per date "
                    "precedenti usa sommario(data, serie)."
                ),
                "pubblicazioni": [
                    {
                        "codice": i.codice,
                        "serie": i.serie.value,
                        "data": i.data.isoformat(),
                        "titolo": i.titolo,
                        "riassunto": _short(i.riassunto, 300),
                        "link": i.link,
                    }
                    for i in shown
                ],
            },
            [feed.link] + [i.link for i in shown[:5]],
        )

    # --- 2. sommario ----------------------------------------------------------------

    async def sommario(self, data: str, serie: str = "SG") -> dict[str, Any]:
        d = _parse_date(data)
        if d is None:
            raise ServiceError(
                "Serve la data del numero, nel formato AAAA-MM-GG (ad esempio 2026-10-03). "
                "Se non la conosci usa ultime_pubblicazioni: elenca i numeri piu' recenti."
            )
        s = _parse_serie(serie, Serie.SG)
        assert s is not None
        som = self._cache.get_sommario(d, s)
        from_cache = som is not None
        if som is None:
            numero = await resolve_numero(self._client, d, s, self._cache)
            raw = await self._client.get_sommario(d, s, numero)
            som = self._parser.parse_sommario(raw.content, s, d, numero, self._base)
            if not som.voci:
                raise ServiceError(
                    f"Il sommario del {d.isoformat()} (serie {s.value}) e' vuoto. Prova con un "
                    "altro giorno o un'altra serie, oppure usa ultime_pubblicazioni."
                )
            self._cache.put_sommario(som)
        voci = som.voci[: self._limits.max_sommario_voci]
        return self._result(
            {
                "serie": s.value,
                "data": d.isoformat(),
                "numero": som.numero,
                "link_numero": som.link,
                "link_pdf": som.link_pdf,
                "totale_voci": len(som.voci),
                "troncato": len(som.voci) > len(voci),
                "dalla_cache": from_cache,
                "voci": [
                    {
                        "codice": v.codice,
                        "titolo": v.titolo,
                        "emettitore": v.emettitore,
                        "rubrica": v.rubrica,
                        "link": v.link,
                    }
                    for v in voci
                ],
            },
            [som.link, som.link_pdf],
        )

    # --- 3. leggi_atto --------------------------------------------------------------

    def _locate(
        self, codice: str, serie: Serie | None, data: date | None
    ) -> tuple[Serie, date | None, bool]:
        """Work out (series, date) for a code. Last item tells whether the series was a guess."""
        known: tuple[Serie, date] | None = None
        finder = getattr(self._cache, "find_codice", None)
        if finder is not None:
            known = finder(codice)
        if known is not None and (serie is None or serie == known[0]):
            return known[0], data or known[1], False
        if serie is not None:
            return serie, data, False
        inferred = _LETTER_TO_SERIE.get(codice[2:3]) if codice[:2].isdigit() else None
        if inferred is not None:
            return inferred, data, False
        return Serie.SG, data, True

    async def _lookup_date(
        self, codice: str, s_arg: Serie | None, s: Serie, guessed: bool
    ) -> tuple[Serie, date] | None:
        """Find a code in the latest feeds: at most two requests, never an archive crawl."""
        if s_arg is not None:
            candidates = [s_arg]
        elif not guessed:
            candidates = [s]  # series inferred from the code letter
        else:
            candidates = [Serie.SG, Serie.S4]
        for cand in candidates[:2]:
            try:
                feed, _ = await self._feed(cand)
            except GuError:
                return None  # offline or failing site: fall back to the guidance error
            for item in feed.items:
                if item.codice == codice:
                    return item.serie, item.data
        return None

    async def leggi_atto(
        self,
        codice: str,
        data: str | None = None,
        serie: str | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        codice = (codice or "").strip().upper()
        if not _CODICE.match(codice):
            raise ServiceError(
                f"Il codice '{codice}' non sembra valido. Il codice dell'atto e' quello tra "
                "parentesi in fondo alla scheda, ad esempio 26A05182 (due cifre dell'anno, una "
                "lettera, cinque cifre). Se non ce l'hai, cercalo con cerca o "
                "ultime_pubblicazioni usando qualche parola del titolo."
            )
        if offset < 0:
            raise ServiceError("L'offset non puo' essere negativo: usa 0 per leggere dall'inizio.")
        s_arg, d_arg = _parse_serie(serie), _parse_date(data)

        atto = self._cache.get_atto(codice)
        from_cache = atto is not None and bool(atto.testo)
        if atto is None or not atto.testo:
            s, d, guessed = self._locate(codice, s_arg, d_arg)
            if d is None:
                found = await self._lookup_date(codice, s_arg, s, guessed)
                if found is not None:
                    s, d, guessed = found[0], found[1], False
            if d is None:
                raise ServiceError(
                    f"Non riesco a risalire a quando e' stato pubblicato l'atto {codice}: non "
                    "compare tra le pubblicazioni recenti. Non serve che tu lo sappia: cerca "
                    "l'atto con qualche parola del titolo (cerca, o ultime_pubblicazioni per "
                    "le novita'), poi riprova. Se conosci il giorno di pubblicazione, "
                    "indicalo nel parametro 'data' (AAAA-MM-GG)."
                )
            atto = await self._fetch_atto(codice, d, s, guessed)
        return self._atto_result(atto, offset, from_cache)

    async def _fetch_atto(self, codice: str, d: date, s: Serie, guessed: bool) -> Atto:
        try:
            scheda = await self._client.get_atto_scheda(codice, d, s)
        except GuNotFoundError:
            hint = (
                " Se l'atto non e' della Serie Generale indica la serie nel parametro 'serie'."
                if guessed
                else ""
            )
            raise ServiceError(
                f"Non trovo l'atto {codice} nella serie {s.value} del {d.isoformat()}. "
                "Controlla di aver copiato bene il codice; se non sei sicuro, cercalo con "
                f"cerca o ultime_pubblicazioni usando parole del titolo.{hint}"
            ) from None
        # The text URL needs the kind of provision, which only the scheda tells.
        tipo = self._parser.parse_atto(scheda.content, b"", codice, s, d, self._base).tipo
        testo = await self._client.get_atto_testo(codice, d, s, tipo)
        atto = self._parser.parse_atto(scheda.content, testo.content, codice, s, d, self._base)
        atto = replace(atto, scaricato_il=self._now())
        if atto.testo:
            self._cache.put_atto(atto)
        return atto

    def _atto_result(self, atto: Atto, offset: int, from_cache: bool) -> dict[str, Any]:
        total = len(atto.testo)
        if offset > total:
            raise ServiceError(
                f"L'offset {offset} supera la lunghezza del testo ({total} caratteri): "
                "usa un valore piu' basso, oppure 0 per ripartire dall'inizio."
            )
        end = min(total, offset + self._limits.max_chars)
        chunk = atto.testo[offset:end]
        next_offset = end if end < total else None
        if next_offset is not None:
            chunk += (
                f"\n\n[... testo troncato: mostrati i caratteri {offset}-{end} di {total}. "
                f"Per continuare richiama leggi_atto con offset={end}. ...]"
            )
        nota = (
            ""
            if atto.testo
            else (
                "Il testo non e' disponibile in forma elettronica qui: apri il link ufficiale "
                "per leggerlo sul sito."
            )
        )
        return self._result(
            {
                "codice": atto.codice,
                "serie": atto.serie.value,
                "data": atto.data.isoformat(),
                "titolo": atto.titolo,
                "emettitore": atto.emettitore,
                "tipo": atto.tipo,
                "numero_gazzetta": atto.numero_gu,
                "testo": chunk,
                "caratteri_totali": total,
                "offset": offset,
                "prossimo_offset": next_offset,
                "troncato": next_offset is not None,
                "dalla_cache": from_cache,
                "nota": nota,
                "link": atto.link,
            },
            [atto.link],
        )

    # --- recent issues (cold start) ---------------------------------------------------

    def _cached_issues(self, serie: Serie, since: date, until: date) -> list[Sommario]:
        """Sommari already in the local cache for the days in [since, until], newest first."""
        found: list[Sommario] = []
        day = until
        while day >= since:
            som = self._cache.get_sommario(day, serie)
            if som is not None:
                found.append(som)
            day -= timedelta(days=1)
        return found

    async def ensure_recent_sommari(
        self, serie: Serie, max_issues: int | None = None
    ) -> RecentIssues:
        """Make sure the newest issues of ``serie`` are in the local cache.

        One request for the "last 30 days" index (cached for an hour), then one request per
        issue not yet cached, newest first, never more than ``Limits.max_recent_issues``.
        The issue number comes from the index: nothing is guessed. Issues never change, so
        a cached one costs nothing. Failures on single issues are reported, not raised.
        """
        default = (
            self._limits.recent_issues_s4 if serie == Serie.S4 else self._limits.recent_issues_sg
        )
        wanted = max(1, min(max_issues if max_issues else default, self._limits.max_recent_issues))
        today = self._today()
        notes: list[str] = []
        requests = 0
        try:
            raw = await self._client.get_elenco_30giorni(serie)
        except UnsupportedSerieError:
            raise
        except GuError as exc:
            notes.append(
                "Non sono riuscito a leggere l'elenco dei numeri degli ultimi 30 giorni "
                f"({user_message(exc)}): uso solo i numeri gia' presenti nella cache locale."
            )
            cached = self._cached_issues(serie, today - timedelta(days=30), today)[:wanted]
            return RecentIssues(serie, cached, 0, notes, today, completo=False)
        if not raw.from_cache:
            requests += 1
        issues = self._parser.parse_elenco_30giorni(raw.content)[:wanted]
        if not issues:
            notes.append("L'elenco dei numeri degli ultimi 30 giorni risulta vuoto o illeggibile.")
        sommari: list[Sommario] = []
        mancanti: list[date] = []
        failures = 0
        for d, numero in issues:
            som = self._cache.get_sommario(d, serie)
            if som is None:
                if failures >= 3:  # the site is struggling: stop asking
                    notes.append(f"Numero {numero} del {d.isoformat()} non caricato.")
                    mancanti.append(d)
                    continue
                try:
                    page = await self._client.get_sommario(d, serie, numero)
                except GuError as exc:
                    failures += 1
                    notes.append(
                        f"Numero {numero} del {d.isoformat()} non caricato ({user_message(exc)})."
                    )
                    mancanti.append(d)
                    continue
                if not page.from_cache:
                    requests += 1
                som = self._parser.parse_sommario(page.content, serie, d, numero, self._base)
                if not som.voci:
                    # an empty page (maintenance, error served with status 200) must not stay
                    # cached for 30 days: it is asked again next time
                    self._cache.delete_http(self._client.url_sommario(d, serie, numero))
                    notes.append(f"Il numero {numero} del {d.isoformat()} risulta vuoto: saltato.")
                    mancanti.append(d)
                    continue
                self._cache.put_sommario(som)
            sommari.append(som)
        return RecentIssues(
            serie, sommari, requests, notes, today, mancanti=mancanti, completo=bool(issues)
        )

    async def _extend_year(self, serie: Serie, max_issues: int | None = None) -> str:
        """Load one block of older issues, going back from the end of the recent cached run.

        Issue numbers are sequential within a year, so the number before ``n`` is ``n - 1``;
        only the date is guessed (1 to 4 days earlier) and every page is verified. The block is
        capped (``Limits.older_block``) and a call that finds nothing to do costs nothing.
        Returns the progress sentence for the answer.
        """
        today = self._today()
        limit = today - timedelta(days=self._limits.year_days)
        cached = self._cached_issues(serie, limit, today)
        if not cached:
            return "Periodo esteso all'anno: nessun numero recente in cache da cui partire."
        block = max_issues or self._limits.older_block
        # Start from the end of the unbroken run of numbers that begins at the newest issue: an
        # old issue opened earlier must not hide the gap between it and the recent ones.
        current = cached[0]
        for older in cached[1:]:
            if older.numero != current.numero - 1:
                break
            current = older
        added = 0
        problem = ""
        while added < block and current.data > limit:
            numero = current.numero - 1
            if numero < 1:
                problem = "arrivato al primo numero dell'anno: i numeri dell'anno prima non vengono ricostruiti"
                break
            found: Sommario | None = None
            for back in range(1, 5):
                day = current.data - timedelta(days=back)
                known = self._cache.get_sommario(day, serie)
                if known is not None and known.numero == numero:
                    found = known
                    break
                try:
                    page = await self._client.get_sommario(day, serie, numero)
                except GuNotFoundError:
                    continue
                except GuError as exc:
                    problem = f"errore di rete ({user_message(exc)})"
                    break
                if not sommario_matches(page.content, day, numero):
                    continue
                parsed = self._parser.parse_sommario(page.content, serie, day, numero, self._base)
                if parsed.voci:
                    self._cache.put_sommario(parsed)
                    found = parsed
                    added += 1
                break
            if problem:
                break
            if found is None:
                problem = (
                    f"numero {numero} non trovato nei 4 giorni prima del {current.data.isoformat()}"
                )
                break
            current = found
        reached = current.data
        if reached <= limit:
            return (
                f"Cache locale della {serie.value} completa fino al {reached.isoformat()} "
                f"(un anno): aggiunti {added} numeri."
            )
        missing = (reached - limit).days
        text = (
            f"Cache locale della {serie.value} estesa fino al {reached.isoformat()}: aggiunti "
            f"{added} numeri, mancano circa {missing} giorni per coprire un anno. Ripeti la "
            "ricerca con periodo='anno' per proseguire."
        )
        return text + (f" (Interrotto: {problem}.)" if problem else "")

    # --- 4. cerca_concorsi ----------------------------------------------------------

    async def cerca_concorsi(
        self,
        parole_chiave: str,
        regione: str | None = None,
        aperti: bool = True,
        includi_altri_atti: bool = False,
        limite: int = 30,
    ) -> dict[str, Any]:
        if not normalize(parole_chiave or ""):
            raise ServiceError("Indica almeno una parola chiave (ad esempio 'infermiere').")
        match = keyword_matcher(parole_chiave)
        reg = normalizza_regione(regione)  # ValueError (Italian) if not recognised
        limite = max(1, min(int(limite), self._limits.max_search_results))

        recent = await self.ensure_recent_sommari(Serie.S4)
        today = self._today()
        cutoff = today - timedelta(days=self._limits.concorsi_window_days)
        sommari = [s for s in recent.sommari if s.data >= cutoff]
        if not aperti:  # older issues already in the cache: no extra request
            known = {s.data for s in sommari}
            older = self._cached_issues(Serie.S4, today - timedelta(days=365), cutoff)
            sommari += [s for s in older if s.data not in known]
        sommari.sort(key=lambda s: s.data, reverse=True)

        examined = bandi_examined = unknown_region = 0
        matches: list[dict[str, Any]] = []
        seen: set[str] = set()
        for som in sommari:
            for v in som.voci:
                if v.codice in seen:
                    continue
                seen.add(v.codice)
                examined += 1
                tipo = classify(v.titolo)
                is_bando = tipo in BANDI
                bandi_examined += is_bando
                if not (is_bando or includi_altri_atti):
                    continue
                if not match(f"{v.titolo} {v.emettitore} {v.rubrica}"):
                    continue
                area = regione_ente(v.emettitore, v.titolo)
                if reg is not None and area != reg:
                    unknown_region += area is None
                    continue
                matches.append(
                    {
                        "codice": v.codice,
                        "ente": v.emettitore,
                        "oggetto": v.titolo,
                        "tipo": tipo,
                        "posti": estrai_posti(v.titolo),
                        "data_gu": som.data.isoformat(),
                        "numero_gu": som.numero,
                        "regione": area,
                        "link": v.link,
                    }
                )
        shown = matches[:limite]
        note = list(recent.notes)
        if reg is not None:
            note.append(
                f"Regione non determinata per {unknown_region} atti che corrispondono alle parole "
                "chiave: non sono mostrati. Ripeti la ricerca senza regione per vederli."
                if unknown_region
                else "Regione non determinata: nessun atto."
            )
        if len(matches) > len(shown):
            note.append(f"Mostrati {len(shown)} risultati su {len(matches)}: aumenta 'limite'.")
        if not sommari:
            note.append(
                "Nessun numero della 4a Serie Speciale disponibile: nessun bando esaminato."
            )
        return self._result(
            {
                "parole_chiave": parole_chiave.strip(),
                "regione": reg,
                "aperti": aperti,
                "includi_altri_atti": includi_altri_atti,
                "copertura": _coverage_text(
                    "4a Serie Speciale (Concorsi ed esami)", sommari, bandi_examined, examined
                ),
                "numeri_esaminati": [
                    {"data": s.data.isoformat(), "numero": s.numero} for s in sommari
                ],
                "bandi_esaminati": bandi_examined,
                "atti_esaminati": examined,
                "richieste_effettuate": recent.richieste,
                "regione_non_determinata": unknown_region if reg is not None else None,
                "avviso_lettura": (
                    "I dati sono estratti dal solo titolo e dall'ente del sommario: leggi sempre "
                    "il bando completo (requisiti, scadenza, modalita' di domanda; il termine e' "
                    "di norma 30 giorni dalla pubblicazione) sul sito ufficiale della Gazzetta "
                    "Ufficiale o dell'ente. La regione e' stimata dal nome dell'ente."
                ),
                "note": note,
                "totale": len(matches),
                "mostrati": len(shown),
                "risultati": shown,
            },
            [s.link for s in sommari[:3]] + [h["link"] for h in shown[:5]] or [self._base],
        )

    # --- 5. rimando_normattiva ------------------------------------------------------

    def rimando_normattiva(self, atto: str) -> dict[str, Any]:
        link = self._linker.link_for(atto)  # ValueError carries the Italian help text
        return self._result(
            {"atto": link.atto, "urn": link.urn, "link_normattiva": link.link, "nota": link.nota},
            [link.link, self._base],
        )

    async def _search_archives(
        self,
        testo: str,
        filtri: SearchFilters,
        serie: Serie | None,
        hits: list[SearchHit],
        note: list[str],
    ) -> tuple[list[SearchHit], list[str]]:
        """Add results from the archives that are switched on; local hits come first.

        Each archive costs one request, is rate limited and cached, and a failure is only a
        note. Duplicates (same act code) are dropped, keeping the local hit.
        """
        merged = list(hits)
        seen = {h.codice for h in merged}
        used: list[str] = []
        repealed: set[str] = set()
        sources = [
            (self._archivio, "atti normativi dal sito Normattiva (open data), per titolo"),
            (self._ricerca_gu, "ricerca avanzata del sito della Gazzetta Ufficiale"),
        ]
        for source, label in sources:
            if source is None or serie not in (None, Serie.SG):
                continue
            try:
                found, total, extra, abrogati = await source.cerca(testo, filtri)
            except GuError as exc:
                note.append(f"Ricerca nell'archivio non riuscita ({label}): {user_message(exc)}")
                continue
            note.extend(extra)
            repealed |= abrogati
            used.append(f"{label} ({total} atti trovati, mostrati i piu' pertinenti)")
            for h in found:
                if h.codice not in seen:
                    seen.add(h.codice)
                    merged.append(h)
        groups = word_groups(testo)  # best matches first, whatever the source
        merged.sort(key=lambda h: -count_matches(h.titolo, groups))
        if filtri.solo_vigenti and repealed:
            kept = [h for h in merged if h.origine != "cache" or h.codice not in repealed]
            if len(kept) < len(merged):
                note.append(
                    f"Esclusi {len(merged) - len(kept)} atti della cache locale perche' abrogati."
                )
            merged = kept
        return merged[: filtri.limite], used

    # --- 6. cerca -------------------------------------------------------------------

    async def cerca(
        self,
        testo: str,
        serie: str | None = None,
        tipo: str | None = None,
        dal: str | None = None,
        al: str | None = None,
        limite: int = 20,
        aggiorna: bool = True,
        solo_vigenti: bool = True,
        periodo: str | None = None,
    ) -> dict[str, Any]:
        if not (testo or "").strip():
            raise ServiceError("Indica il testo da cercare.")
        limite = max(1, min(int(limite), self._limits.max_search_results))
        s = _parse_serie(serie)
        filtri = SearchFilters(
            serie=s,
            tipo=tipo.strip() if tipo and tipo.strip() else None,
            dal=_parse_date(dal, "dal"),
            al=_parse_date(al, "al"),
            limite=limite,
            solo_vigenti=solo_vigenti,
        )
        anno = (periodo or "").strip().lower() in {"anno", "ultimo anno", "12 mesi"}
        if (periodo or "").strip() and not anno and periodo.strip().lower() != "recenti":
            raise ServiceError("Il periodo puo' essere 'recenti' (predefinito) oppure 'anno'.")
        loaded: list[RecentIssues] = []
        note: list[str] = []
        if aggiorna:
            targets = [Serie.SG, Serie.S4] if s is None else [s] if s in _REFRESHABLE else []
            for target in targets:
                try:
                    loaded.append(await self.ensure_recent_sommari(target))
                except GuError as exc:
                    note.append(
                        f"Aggiornamento della serie {target.value} non riuscito: "
                        f"{user_message(exc)}"
                    )
            for r in loaded:
                note.extend(r.notes)
            if anno and Serie.SG in targets:
                note.append(await self._extend_year(Serie.SG))
            if s is not None and not targets:
                note.append(
                    f"L'aggiornamento automatico vale per SG e S4: per la serie {s.value} "
                    "la ricerca usa solo la cache locale."
                )
        stats = getattr(self._cache, "stats", None)
        if stats is not None and stats().get("search_entries", 1) == 0:
            return self._result(
                {
                    "totale": 0,
                    "risultati": [],
                    "note": note,
                    "messaggio": (
                        "La cache locale e' vuota: la ricerca copre solo cio' che hai gia' "
                        "consultato. Usa ultime_pubblicazioni, sommario o leggi_atto per "
                        "scaricare qualcosa (oppure cerca con aggiorna=true), poi riprova."
                    ),
                },
                [self._base],
            )
        hits = self._cache.search(testo, filtri)
        fonti_archivio: list[str] = []
        if aggiorna:
            hits, fonti_archivio = await self._search_archives(testo, filtri, s, hits, note)
        if not hits:
            note.append(
                "Nessun risultato nei numeri recenti, nella cache locale e nell'archivio: prova "
                "parole diverse, indica un periodo con dal/al, oppure usa la ricerca del sito "
                "ufficiale (https://www.gazzettaufficiale.it)."
            )
        if loaded:
            parti = [
                f"{r.serie.value} dal {r.dal.isoformat()} al {r.al.isoformat()} "
                f"({len(r.sommari)} numeri)"
                for r in loaded
                if r.sommari
            ]
            copertura = (
                "Cercato nei titoli e negli enti degli atti dei numeri piu' recenti"
                + (f" ({'; '.join(parti)})" if parti else "")
                + " e in quanto gia' presente nella cache locale. NON viene cercato il testo "
                "completo degli atti, salvo quelli gia' letti con leggi_atto."
            )
        else:
            copertura = (
                "La ricerca copre solo i contenuti gia' presenti nella cache locale "
                "(feed, sommari e atti consultati finora), non l'intero archivio."
            )
        if fonti_archivio:
            copertura += (
                " In piu' e' stato interrogato l'archivio: "
                + "; ".join(fonti_archivio)
                + ". Gli atti con origine diversa da 'cache' vanno letti con leggi_atto "
                "indicando anche la data."
            )
        fonte = [h.link for h in hits[:5]] or [r.sommari[0].link for r in loaded if r.sommari]
        return self._result(
            {
                "copertura": copertura,
                "numeri_caricati": [
                    {
                        "serie": r.serie.value,
                        "dal": r.dal.isoformat() if r.sommari else None,
                        "al": r.al.isoformat() if r.sommari else None,
                        "numeri": len(r.sommari),
                        "richieste_effettuate": r.richieste,
                        "mancanti": [d.isoformat() for d in r.mancanti],
                        "completo": r.completo,
                    }
                    for r in loaded
                ],
                "note": note,
                "totale": len(hits),
                "risultati": [_hit(h) for h in hits],
            },
            fonte or [self._base],
        )


@dataclass(frozen=True)
class RecentIssues:
    """Outcome of :meth:`GazzettaService.ensure_recent_sommari`."""

    serie: Serie
    sommari: list[Sommario]  # newest first, all in the local cache
    richieste: int  # network requests made (cache hits are free)
    notes: list[str]
    today: date
    # days of the issues that were expected but could not be loaded (error, empty page)
    mancanti: list[date] = field(default_factory=list)
    # False when the index of recent issues could not be read: the coverage is unknown
    completo: bool = True

    @property
    def dal(self) -> date:
        return min((s.data for s in self.sommari), default=self.today)

    @property
    def al(self) -> date:
        return max((s.data for s in self.sommari), default=self.today)


_REFRESHABLE = (Serie.SG, Serie.S4)


def _coverage_text(nome: str, sommari: list[Sommario], bandi: int, atti: int) -> str:
    if not sommari:
        return f"Nessun numero della {nome} esaminato."
    dal = min(s.data for s in sommari).isoformat()
    al = max(s.data for s in sommari).isoformat()
    return (
        f"Numeri dal {dal} al {al} della {nome} ({len(sommari)} numeri, {bandi} bandi esaminati, "
        f"{atti} atti in totale). Cercati solo titolo ed ente di ogni atto; i bandi piu' vecchi "
        "o non ancora pubblicati non compaiono."
    )


def _hit(h) -> dict[str, Any]:
    return {
        "codice": h.codice,
        "serie": h.serie.value,
        "data": h.data.isoformat(),
        "titolo": h.titolo,
        "estratto": h.estratto,
        "link": h.link,
        "punteggio": round(h.punteggio, 3),
        "origine": h.origine,
    }


def build_service(settings: Settings | None = None) -> GazzettaService:
    """Default wiring from the environment (GAZZETTA_MCP_*)."""
    settings = settings or Settings.from_env()
    cache = SqliteCache.from_settings(settings)
    client = GuClient(settings, cache=cache)
    limits = Limits()
    raw_max = os.environ.get("GAZZETTA_MCP_MAX_CHARS")
    if raw_max:
        try:
            limits = replace(limits, max_chars=max(1000, int(raw_max)))
        except ValueError:
            pass
    raw_sg = os.environ.get("GAZZETTA_MCP_RECENT_ISSUES_SG")
    if raw_sg:
        try:
            limits = replace(
                limits, recent_issues_sg=max(1, min(int(raw_sg), limits.max_recent_issues))
            )
        except ValueError:
            pass
    normattiva_limiter = RateLimiter(settings.requests_per_second)
    archivio = (
        ArchivioClient(settings, cache=cache, limiter=normattiva_limiter)
        if settings.archivio_normattiva
        else None
    )
    ricerca_gu = RicercaGuClient(settings, cache=cache) if settings.ricerca_gu else None
    closers = (client.aclose, cache.close)
    closers += tuple(c.aclose for c in (archivio, ricerca_gu) if c is not None)
    return GazzettaService(
        archivio=archivio,
        ricerca_gu=ricerca_gu,
        normattiva_limiter=normattiva_limiter,
        client=client,
        parser=GuParser(),
        cache=cache,
        linker=NormattivaLinkBuilder(settings),
        settings=settings,
        limits=limits,
        closers=closers,
    )
