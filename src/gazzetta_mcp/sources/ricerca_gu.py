"""Advanced search form of the GU site, used only on request and only when switched on.

Off by default (``GAZZETTA_MCP_RICERCA_GU=1`` enables it): the terms of use of the site do not
mention automated use of the form, so it stays opt-in until confirmed with the publisher.
One GET of the form (it sets the session cookie) and one POST per search, first page only.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx

from ..config import Settings
from ..interfaces import Cache
from ..models import ArchiveResult, RawPage, SearchFilters
from ..parsing.ricerca import parse_ricerca
from ..searchtext import search_words
from .gu import GuHttpError
from .ratelimit import RateLimiter

SEARCH_TTL_SECONDS = 24 * 3600
FIRST_YEAR = 1988  # the site searches the full text from 1988


class RicercaGuClient:
    """Implements :class:`ArchiveSearch` on top of the GU advanced search form."""

    def __init__(
        self,
        settings: Settings | None = None,
        cache: Cache | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._settings = settings or Settings()
        self._base = self._settings.gu_base_url.rstrip("/")
        self._form_url = (
            f"{self._base}/ricerca/atto/serie_generale/originario?reset=true&normativi=false"
        )
        self._post_url = f"{self._base}/do/ricerca/atto/serie_generale/originario/0"
        self._cache = cache
        self._limiter = limiter or RateLimiter(self._settings.requests_per_second)
        self._http = httpx.AsyncClient(  # keeps the cookies of the form between calls
            transport=transport,
            timeout=self._settings.timeout_seconds,
            headers={"User-Agent": self._settings.user_agent},
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    def _fields(self, testo: str, filtri: SearchFilters) -> dict[str, str]:
        today = datetime.now(timezone.utc).year
        return {
            "cerca": "Cerca",
            "attiNumerati": "false",
            "tipoRicercaTitolo": "ALL_WORDS",
            "titolo": "",
            "titoloNot": "",
            "tipoRicercaTesto": "ALL_WORDS",
            "testo": " ".join(search_words(testo)),
            "testoNot": "",
            "annoPubblicazioneDa": str(filtri.dal.year if filtri.dal else FIRST_YEAR),
            "annoPubblicazioneA": str(filtri.al.year if filtri.al else today),
        }

    async def cerca(self, testo: str, filtri: SearchFilters) -> ArchiveResult:
        if not search_words(testo):
            return ArchiveResult([], 0, [])
        fields = self._fields(testo, filtri)
        body = urlencode(fields)
        key = f"{self._post_url}#{hashlib.sha256(body.encode()).hexdigest()}"
        content = None
        if self._cache is not None:
            hit = self._cache.get_http(key, SEARCH_TTL_SECONDS)
            if hit is not None:
                content = hit.content
        if content is None:
            try:
                await self._limiter.acquire()
                await self._http.get(self._form_url)  # session cookie of the form
                await self._limiter.acquire()
                response = await self._http.post(
                    self._post_url,
                    content=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.HTTPError as exc:
                raise GuHttpError(f"GU search failed: {exc}") from exc
            if response.status_code != 200:
                raise GuHttpError(f"GU search: HTTP status {response.status_code}")
            content = response.content
            if self._cache is not None:
                self._cache.put_http(
                    RawPage(
                        url=key,
                        content=content,
                        content_type="text/html",
                        fetched_at=datetime.now(timezone.utc),
                    )
                )
        hits, total = parse_ricerca(content, self._base)
        if filtri.dal:
            hits = [h for h in hits if h.data >= filtri.dal]
        if filtri.al:
            hits = [h for h in hits if h.data <= filtri.al]
        return ArchiveResult(hits[: filtri.limite], total, [])
