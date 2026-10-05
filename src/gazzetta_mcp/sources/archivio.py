"""Archive search through the Normattiva Open Data API (CC BY 4.0, no API key).

One POST per search to ``ricerca/avanzata``. The API matches *any* of the title words and
sorts by date, so the ranking (how many words an act matches) is done here. It covers
normative acts only: notices, competitions and most ministerial decrees are not in it.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone

import httpx

from ..config import Settings
from ..interfaces import Cache
from ..models import RawPage, SearchFilters, SearchHit, Serie
from ..searchtext import STOPWORDS, stem
from .gu import GuError, GuHttpError
from .ratelimit import RateLimiter

_WORD = re.compile(r"\w+", re.UNICODE)
SEARCH_TTL_SECONDS = 24 * 3600
PAGE_SIZE = 40
ORIGINE = "normattiva"


def search_words(text: str) -> list[str]:
    """Meaningful words of a query: lowercase, no stopwords (kept if nothing else is left)."""
    words = [w.lower() for w in _WORD.findall(text)]
    return [w for w in words if w not in STOPWORDS] or words


def _matches(title: str, words: list[str]) -> int:
    low = title.lower()
    return sum(1 for w in words if stem(w) in low)


class ArchivioClient:
    """Searches the archive of normative acts. Rate limited, cached, identifies itself."""

    def __init__(
        self,
        settings: Settings | None = None,
        cache: Cache | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._settings = settings or Settings()
        self._url = self._settings.normattiva_api_url.rstrip("/") + "/ricerca/avanzata"
        self._cache = cache
        self._limiter = limiter or RateLimiter(self._settings.requests_per_second)
        self._http = httpx.AsyncClient(
            transport=transport,
            timeout=self._settings.timeout_seconds,
            headers={
                "User-Agent": self._settings.user_agent,
                "Accept": "application/json",
            },
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    def _body(self, testo: str, filtri: SearchFilters) -> dict:
        body: dict = {
            "orderType": "recente",
            "titoloRicerca": " ".join(search_words(testo)),
            "paginazione": {"paginaCorrente": 1, "numeroElementiPerPagina": PAGE_SIZE},
        }
        if filtri.tipo:
            body["denominazioneAtto"] = filtri.tipo.upper()
        if filtri.dal:
            body["dataInizioPubProvvedimento"] = filtri.dal.isoformat()
        if filtri.al:
            body["dataFinePubProvvedimento"] = filtri.al.isoformat()
        return body

    async def cerca(self, testo: str, filtri: SearchFilters) -> tuple[list[SearchHit], int]:
        """Return (hits ranked by matched words then date, total found by the API)."""
        words = search_words(testo)
        if not words:
            return [], 0
        body = self._body(testo, filtri)
        payload = json.dumps(body, sort_keys=True)
        key = f"{self._url}#{hashlib.sha256(payload.encode()).hexdigest()}"
        data = None
        if self._cache is not None:
            hit = self._cache.get_http(key, SEARCH_TTL_SECONDS)
            if hit is not None:
                data = json.loads(hit.content)
        if data is None:
            await self._limiter.acquire()
            try:
                response = await self._http.post(self._url, content=payload,
                                                 headers={"Content-Type": "application/json"})
            except httpx.HTTPError as exc:
                raise GuHttpError(f"Normattiva search failed: {exc}") from exc
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
        total = int(data.get("numeroAttiTrovati") or 0)
        hits: list[tuple[int, SearchHit]] = []
        for a in data.get("listaAtti") or []:
            codice = a.get("codiceRedazionale")
            if not codice or not a.get("dataGU"):
                continue
            titolo = " ".join(str(a.get("titoloAtto") or "").strip("[] ").split())
            descr = a.get("descrizioneAtto") or ""
            data_gu = date.fromisoformat(a["dataGU"])
            n = _matches(titolo + " " + descr, words)
            hits.append(
                (
                    n,
                    SearchHit(
                        codice=codice,
                        serie=Serie.SG,
                        data=data_gu,
                        titolo=f"{descr}: {titolo}" if descr else titolo,
                        estratto=f"Pubblicato nella GU n. {a.get('numeroGU')} del {data_gu:%d/%m/%Y}",
                        link=self._gu_link(codice, data_gu, a),
                        punteggio=float(n),
                        origine=ORIGINE,
                    ),
                )
            )
        hits.sort(key=lambda t: (-t[0], -t[1].data.toordinal()))
        return [h for _, h in hits[: filtri.limite]], total

    def _gu_link(self, codice: str, data: date, a: dict) -> str:
        base = self._settings.gu_base_url.rstrip("/")
        return f"{base}/eli/id/{data:%Y/%m/%d}/{codice}/SG"
