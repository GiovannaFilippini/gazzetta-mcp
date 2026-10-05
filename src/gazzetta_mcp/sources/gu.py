"""HTTP client for gazzettaufficiale.it (SourceClient) and the issue-number resolver."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

import httpx

from ..config import Settings
from ..interfaces import Cache, SourceClient
from ..models import ATTO_URL_SEGMENT, RawPage, Serie
from .ratelimit import RateLimiter

# Issues and acts never change once published: cache them for a long time.
STATIC_TTL_SECONDS = 30 * 24 * 3600


class GuError(Exception):
    """Base class for GU client errors."""


class GuNotFoundError(GuError):
    """The requested page does not exist (HTTP 404)."""


class GuHttpError(GuError):
    """Network failure or unexpected HTTP status."""


class UnsupportedSerieError(GuError):
    """The text URL segment for this series is not known."""


class NumeroNotFoundError(GuError):
    """The issue number for a (date, series) could not be determined."""


class GuClient:
    """Implements :class:`SourceClient`. Fetches only what is explicitly requested."""

    def __init__(
        self,
        settings: Settings | None = None,
        cache: Cache | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._settings = settings or Settings()
        self._base = self._settings.gu_base_url.rstrip("/")
        self._cache = cache
        self._limiter = limiter or RateLimiter(self._settings.requests_per_second)
        self._http = httpx.AsyncClient(
            transport=transport,
            timeout=self._settings.timeout_seconds,
            headers={"User-Agent": self._settings.user_agent},
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> GuClient:  # noqa: PYI034
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # --- URL builders -------------------------------------------------------------

    def url_feed(self, serie: Serie) -> str:
        return f"{self._base}/rss/{serie.value}"

    def url_sommario(self, data: date, serie: Serie, numero: int) -> str:
        return f"{self._base}/eli/gu/{data:%Y/%m/%d}/{numero}/{serie.value}/html"

    def url_pdf(self, data: date, serie: Serie, numero: int) -> str:
        return f"{self._base}/eli/gu/{data:%Y/%m/%d}/{numero}/{serie.value}/pdf"

    def url_atto(self, codice: str, data: date, serie: Serie) -> str:
        return f"{self._base}/eli/id/{data:%Y/%m/%d}/{codice}/{serie.value}"

    def url_atto_testo(self, codice: str, data: date, serie: Serie, tipo: str | None) -> str:
        segment = ATTO_URL_SEGMENT.get(serie)
        if not segment:
            raise UnsupportedSerieError(f"The act text URL for series {serie.value} is not known.")
        url = (
            f"{self._base}/atto/{segment}/caricaArticoloDefault/originario"
            f"?atto.dataPubblicazioneGazzetta={data:%Y-%m-%d}"
            f"&atto.codiceRedazionale={quote(codice, safe='')}"
        )
        if tipo:
            url += f"&atto.tipoProvvedimento={quote(tipo, safe='')}"
        return url

    # --- Fetching -----------------------------------------------------------------

    async def get_feed(self, serie: Serie) -> RawPage:
        return await self._fetch(self.url_feed(serie), self._settings.cache_ttl_feed_seconds)

    async def get_sommario(self, data: date, serie: Serie, numero: int) -> RawPage:
        return await self._fetch(self.url_sommario(data, serie, numero), STATIC_TTL_SECONDS)

    async def get_atto_scheda(self, codice: str, data: date, serie: Serie) -> RawPage:
        return await self._fetch(self.url_atto(codice, data, serie), STATIC_TTL_SECONDS)

    async def get_atto_testo(
        self, codice: str, data: date, serie: Serie, tipo: str | None
    ) -> RawPage:
        return await self._fetch(self.url_atto_testo(codice, data, serie, tipo), STATIC_TTL_SECONDS)

    async def _fetch(self, url: str, max_age_seconds: int) -> RawPage:
        if self._cache is not None:
            hit = self._cache.get_http(url, max_age_seconds)
            if hit is not None:
                return RawPage(
                    url=hit.url,
                    content=hit.content,
                    content_type=hit.content_type,
                    fetched_at=hit.fetched_at,
                    from_cache=True,
                )
        await self._limiter.acquire()
        try:
            response = await self._http.get(url)
        except httpx.HTTPError as exc:
            raise GuHttpError(f"Request to {url} failed: {exc}") from exc
        if response.status_code == 404:
            raise GuNotFoundError(f"Not found: {url}")
        if response.status_code != 200:
            raise GuHttpError(f"Unexpected HTTP status {response.status_code} for {url}")
        page = RawPage(
            url=url,
            content=response.content,
            content_type=response.headers.get("content-type", ""),
            fetched_at=datetime.now(timezone.utc),
        )
        if self._cache is not None:
            self._cache.put_http(page)
        return page


# --- Issue number resolution ------------------------------------------------------

_CHANNEL_LINK = re.compile(
    rb"/eli/gu/(\d{4})/(\d{2})/(\d{2})/(\d+)/([A-Za-z0-9]+)(?:/html)?\s*</link>"
)

# Rough share of calendar days with an issue, used only to seed the guesses.
_ISSUES_PER_DAY = {Serie.SG: 6 / 7}
_DEFAULT_ISSUES_PER_DAY = 2 / 7


def parse_feed_channel(raw: bytes) -> tuple[date, int] | None:
    """Return (date, issue number) from the channel ``<link>`` of a GU RSS feed."""
    head = raw.split(b"<item", 1)[0]
    m = _CHANNEL_LINK.search(head)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3])), int(m[4])
    except ValueError:
        return None


def sommario_matches(raw: bytes, data: date, numero: int) -> bool:
    """True if an issue page is the real one (the GU answers 200 for any number).

    A real page carries a permalink with the exact date and number; a bogus number yields
    a stub page without it.
    """
    pattern = rb"dataPubblicazioneGazzetta=%s(?:&amp;|&)numeroGazzetta=%d\b" % (
        data.isoformat().encode(),
        numero,
    )
    return re.search(pattern, raw) is not None


def _candidates(ref_data: date, ref_numero: int, data: date, serie: Serie, n: int) -> list[int]:
    days = (ref_data - data).days
    rate = _ISSUES_PER_DAY.get(serie, _DEFAULT_ISSUES_PER_DAY)
    estimate = max(1, ref_numero - round(days * rate))
    ordered = [estimate]
    step = 1
    while len(ordered) < n and step <= n:
        for cand in (estimate - step, estimate + step):
            if len(ordered) < n and 1 <= cand < ref_numero and cand not in ordered:
                ordered.append(cand)
        step += 1
    return [c for c in ordered if c < ref_numero]


async def resolve_numero(
    client: SourceClient,
    data: date,
    serie: Serie,
    cache: Cache | None = None,
    max_guesses: int = 4,
) -> int:
    """Find the GU issue number for (date, series). See docs/decisioni/010-numero-gazzetta.md.

    Order: local cache, latest RSS feed, then at most ``max_guesses`` verified guesses.
    """
    if cache is not None:
        known = cache.get_sommario(data, serie)
        if known is not None:
            return known.numero

    feed = await client.get_feed(serie)
    channel = parse_feed_channel(feed.content)
    if channel is None:
        raise NumeroNotFoundError(f"Cannot read the issue number from the {serie.value} feed.")
    ref_data, ref_numero = channel
    if data == ref_data:
        return ref_numero
    if data > ref_data:
        raise NumeroNotFoundError(
            f"No issue of series {serie.value} on {data}: the latest is of {ref_data}."
        )
    if ref_data - data > timedelta(days=366):
        raise NumeroNotFoundError(
            f"Date {data} is too far from the latest issue ({ref_data}) to guess the number."
        )

    for numero in _candidates(ref_data, ref_numero, data, serie, max_guesses):
        try:
            page = await client.get_sommario(data, serie, numero)
        except GuNotFoundError:
            continue
        if sommario_matches(page.content, data, numero):
            return numero
    raise NumeroNotFoundError(
        f"Could not determine the issue number of series {serie.value} for {data}. "
        "Try the latest publications tool, or pass the issue number explicitly."
    )
