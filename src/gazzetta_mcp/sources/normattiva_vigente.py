"""Current text of one article through the Normattiva Open Data API (CC BY 4.0, no API key).

One POST per article to ``atto/dettaglio-atto-urn``. The API gives the wording in force today of
one article at a time and no list of the articles of an act, so a whole act cannot be read
reliably (decision 110). Rate limited, cached, identifies itself.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import httpx

from ..config import Settings
from ..interfaces import Cache
from ..models import RawPage
from .gu import GuError, GuHttpError
from .ratelimit import RateLimiter

VIGENTE_TTL_SECONDS = 24 * 3600


class VigenteNotFoundError(GuError):
    """Normattiva has no such act or article (HTTP 400/404 or an empty answer)."""


class NormattivaVigenteClient:
    """Fetches the article in force. Raises GuError subclasses on any failure."""

    def __init__(
        self,
        settings: Settings | None = None,
        cache: Cache | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._settings = settings or Settings()
        self._url = self._settings.normattiva_api_url.rstrip("/") + "/atto/dettaglio-atto-urn"
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

    async def get_articolo(self, urn: str) -> bytes:
        """Raw JSON for ``urn`` (with ``~artN`` for an article; without it the first one)."""
        payload = json.dumps({"urn": urn}, sort_keys=True)
        key = f"{self._url}#{hashlib.sha256(payload.encode()).hexdigest()}"
        if self._cache is not None:
            hit = self._cache.get_http(key, VIGENTE_TTL_SECONDS)
            if hit is not None:
                return hit.content
        await self._limiter.acquire()
        try:
            response = await self._http.post(
                self._url, content=payload, headers={"Content-Type": "application/json"}
            )
        except httpx.HTTPError as exc:
            raise GuHttpError(f"Normattiva article failed: {exc!r}") from exc
        if response.status_code in (400, 404):
            raise VigenteNotFoundError(f"Normattiva article: HTTP status {response.status_code}")
        if response.status_code != 200:
            raise GuHttpError(f"Normattiva article: HTTP status {response.status_code}")
        if self._cache is not None:
            self._cache.put_http(
                RawPage(
                    url=key,
                    content=response.content,
                    content_type="application/json",
                    fetched_at=datetime.now(timezone.utc),
                )
            )
        return response.content
