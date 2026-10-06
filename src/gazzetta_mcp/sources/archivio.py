"""Archive search through the Normattiva Open Data API (CC BY 4.0, no API key).

One POST per search to ``ricerca/avanzata`` (plus one for the repealed acts). The API matches
*any* of the title words and sorts by date, so the ranking (how many words an act matches) is
done here. It covers normative acts only: notices, competitions and most ministerial decrees
are not in it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

import httpx

from ..config import Settings
from ..interfaces import Cache
from ..models import ArchiveResult, RawPage, SearchFilters, SearchHit, Serie
from ..searchtext import count_matches, flatten, search_words, word_groups
from .gu import GuError, GuHttpError
from .ratelimit import RateLimiter

SEARCH_TTL_SECONDS = 24 * 3600
PAGE_SIZE = 40
ABROGATI_PAGE_SIZE = 50
CLASSE_ABROGATO = "3"  # classeProvvedimento: 1 no updates, 2 updated, 3 repealed
ORIGINE = "normattiva"


class ArchivioClient:
    """Searches the archive of normative acts. Rate limited, cached, identifies itself."""

    def __init__(
        self,
        settings: Settings | None = None,
        cache: Cache | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        limiter: RateLimiter | None = None,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._today = today
        self._settings = settings or Settings()
        self._url = self._settings.normattiva_api_url.rstrip("/") + "/ricerca/avanzata"
        self._cache = cache
        self._limiter = limiter or RateLimiter(self._settings.requests_per_second)
        self._http = httpx.AsyncClient(
            transport=transport,
            timeout=self._settings.archivio_timeout_seconds,
            headers={
                "User-Agent": self._settings.user_agent,
                "Accept": "application/json",
            },
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    def _body(self, testo: str, filtri: SearchFilters, dal: date, classe: str | None) -> dict:
        body: dict = {
            "orderType": "recente",
            "titoloRicerca": " ".join(flatten(word_groups(testo))),
            "dataInizioPubProvvedimento": dal.isoformat(),
            "paginazione": {
                "paginaCorrente": 1,
                "numeroElementiPerPagina": PAGE_SIZE if classe is None else ABROGATI_PAGE_SIZE,
            },
        }
        if filtri.tipo:
            body["denominazioneAtto"] = filtri.tipo.upper()
        if filtri.al:
            body["dataFinePubProvvedimento"] = filtri.al.isoformat()
        if classe is not None:
            body["classeProvvedimento"] = classe
        return body

    async def _post(self, body: dict) -> dict:
        """One cached POST. Raises GuError on any failure."""
        payload = json.dumps(body, sort_keys=True)
        key = f"{self._url}#{hashlib.sha256(payload.encode()).hexdigest()}"
        if self._cache is not None:
            hit = self._cache.get_http(key, SEARCH_TTL_SECONDS)
            if hit is not None:
                return json.loads(hit.content)
        await self._limiter.acquire()
        try:
            response = await self._http.post(
                self._url, content=payload, headers={"Content-Type": "application/json"}
            )
        except httpx.HTTPError as exc:
            raise GuHttpError(f"Normattiva search failed: {exc!r}") from exc
        if response.status_code != 200:
            raise GuHttpError(f"Normattiva search: HTTP status {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise GuError("Normattiva search: unreadable answer") from exc
        if self._cache is not None:
            self._cache.put_http(
                RawPage(
                    url=key,
                    content=response.content,
                    content_type="application/json",
                    fetched_at=datetime.now(timezone.utc),
                )
            )
        return data

    async def cerca(self, testo: str, filtri: SearchFilters) -> ArchiveResult:
        """Hits ranked by matched words then date; the repealed ones left out on request.

        Without ``dal`` the period is the last ``archivio_giorni`` days. The repealed acts
        come from a second request (class 3); if it fails the hits are kept and a note says
        that the repealed ones could not be excluded.
        """
        if not search_words(testo):
            return ArchiveResult([], 0, [])
        dal = filtri.dal or self._today() - timedelta(days=self._settings.archivio_giorni)
        main = self._post(self._body(testo, filtri, dal, None))
        if filtri.solo_vigenti:
            data, repealed = await asyncio.gather(
                main,
                self._post(self._body(testo, filtri, dal, CLASSE_ABROGATO)),
                return_exceptions=True,
            )
        else:
            data, repealed = await main, None
        if isinstance(data, BaseException):
            raise data
        note: list[str] = []
        abrogati: set[str] = set()
        if isinstance(repealed, BaseException):
            note.append(
                "Non sono riuscito a controllare quali atti sono stati abrogati: "
                "nei risultati possono comparire anche atti non piu' in vigore."
            )
        elif repealed is not None:
            abrogati = {a.get("codiceRedazionale") for a in repealed.get("listaAtti") or []}
        groups = word_groups(testo)
        total = int(data.get("numeroAttiTrovati") or 0)
        hits: list[tuple[int, SearchHit]] = []
        skipped = 0
        for a in data.get("listaAtti") or []:
            codice = a.get("codiceRedazionale")
            if not codice or not a.get("dataGU"):
                continue
            if codice in abrogati:
                skipped += 1
                continue
            titolo = " ".join(str(a.get("titoloAtto") or "").strip("[] ").split())
            descr = a.get("descrizioneAtto") or ""
            data_gu = date.fromisoformat(a["dataGU"])
            n = count_matches(titolo + " " + descr, groups)
            hits.append(
                (
                    n,
                    SearchHit(
                        codice=codice,
                        serie=Serie.SG,
                        data=data_gu,
                        titolo=f"{descr}: {titolo}" if descr else titolo,
                        estratto=f"Pubblicato nella GU n. {a.get('numeroGU')} del {data_gu:%d/%m/%Y}",
                        link=self._gu_link(codice, data_gu),
                        punteggio=float(n),
                        origine=ORIGINE,
                    ),
                )
            )
        if skipped:
            note.append(f"Esclusi {skipped} atti abrogati.")
        hits.sort(key=lambda t: (-t[0], -t[1].data.toordinal()))
        return ArchiveResult(
            [h for _, h in hits[: filtri.limite]], total, note, frozenset(abrogati)
        )

    def _gu_link(self, codice: str, data: date) -> str:
        base = self._settings.gu_base_url.rstrip("/")
        return f"{base}/eli/id/{data:%Y/%m/%d}/{codice}/SG"
