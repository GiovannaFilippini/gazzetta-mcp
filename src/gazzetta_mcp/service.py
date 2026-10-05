"""Business logic of the MCP server. The tools in ``tools/`` are thin wrappers around this.

Every public method returns a JSON-serialisable dict that always carries ``fonte`` (official
links) and ``avvertenza`` (the disclaimer). Failures raise :class:`ServiceError` with a short
Italian message; use :func:`user_message` to turn any exception into such a message.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .cache.sqlite import CacheError, SqliteCache
from .config import Settings
from .interfaces import Cache, NormattivaLinker, Parser, SourceClient
from .models import DISCLAIMER, Atto, SearchFilters, Serie
from .parsing import GuParser, ParseError
from .sources.gu import (
    GuClient,
    GuError,
    GuHttpError,
    GuNotFoundError,
    NumeroNotFoundError,
    UnsupportedSerieError,
    resolve_numero,
)
from .sources.normattiva import NormattivaLinkBuilder

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

    # --- 4. cerca_concorsi ----------------------------------------------------------

    async def cerca_concorsi(
        self, parole_chiave: str, regione: str | None = None
    ) -> dict[str, Any]:
        if not (parole_chiave or "").strip():
            raise ServiceError("Indica almeno una parola chiave (ad esempio 'istruttore').")
        note: list[str] = []
        fonte = [f"{self._base}/rss/S4"]
        try:
            feed, _ = await self._feed(Serie.S4)
            fonte.insert(0, feed.link)
        except GuError as exc:
            note.append(
                "Non sono riuscito ad aggiornare il feed dei concorsi "
                f"({user_message(exc)}): uso solo la cache locale."
            )
        query = parole_chiave.strip()
        if regione and regione.strip():
            query += f" {regione.strip()}"
        hits = self._cache.search(
            query, SearchFilters(serie=Serie.S4, limite=self._limits.concorsi_results)
        )
        return self._result(
            {
                "parole_chiave": parole_chiave.strip(),
                "regione": regione.strip() if regione and regione.strip() else None,
                "copertura": (
                    "Attenzione: i risultati coprono SOLO quanto e' gia' nella cache locale e "
                    "nell'ultimo feed della 4a Serie Speciale (Concorsi ed esami). Non viene "
                    "esplorato l'archivio della Gazzetta: bandi meno recenti o mai richiesti "
                    "possono non comparire. Il filtro per regione e' una corrispondenza di "
                    "testo sul nome della regione."
                ),
                "note": note,
                "totale": len(hits),
                "risultati": [_hit(h) for h in hits],
            },
            fonte + [h.link for h in hits[:5]],
        )

    # --- 5. rimando_normattiva ------------------------------------------------------

    def rimando_normattiva(self, atto: str) -> dict[str, Any]:
        link = self._linker.link_for(atto)  # ValueError carries the Italian help text
        return self._result(
            {"atto": link.atto, "urn": link.urn, "link_normattiva": link.link, "nota": link.nota},
            [link.link, self._base],
        )

    # --- 6. cerca -------------------------------------------------------------------

    def cerca(
        self,
        testo: str,
        serie: str | None = None,
        tipo: str | None = None,
        dal: str | None = None,
        al: str | None = None,
        limite: int = 20,
    ) -> dict[str, Any]:
        if not (testo or "").strip():
            raise ServiceError("Indica il testo da cercare.")
        limite = max(1, min(int(limite), self._limits.max_search_results))
        filtri = SearchFilters(
            serie=_parse_serie(serie),
            tipo=tipo.strip() if tipo and tipo.strip() else None,
            dal=_parse_date(dal, "dal"),
            al=_parse_date(al, "al"),
            limite=limite,
        )
        stats = getattr(self._cache, "stats", None)
        if stats is not None and stats().get("search_entries", 1) == 0:
            return self._result(
                {
                    "totale": 0,
                    "risultati": [],
                    "messaggio": (
                        "La cache locale e' vuota: la ricerca copre solo cio' che hai gia' "
                        "consultato. Usa prima ultime_pubblicazioni, sommario o leggi_atto per "
                        "scaricare qualcosa, poi riprova."
                    ),
                },
                [self._base],
            )
        hits = self._cache.search(testo, filtri)
        return self._result(
            {
                "copertura": (
                    "La ricerca copre solo i contenuti gia' presenti nella cache locale "
                    "(feed, sommari e atti consultati finora), non l'intero archivio."
                ),
                "totale": len(hits),
                "risultati": [_hit(h) for h in hits],
            },
            [h.link for h in hits[:5]] or [self._base],
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
            limits = Limits(max_chars=max(1000, int(raw_max)))
        except ValueError:
            pass
    return GazzettaService(
        client=client,
        parser=GuParser(),
        cache=cache,
        linker=NormattivaLinkBuilder(settings),
        settings=settings,
        limits=limits,
        closers=(client.aclose, cache.close),
    )
