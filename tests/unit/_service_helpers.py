"""Shared test wiring: a GuClient over httpx.MockTransport serving tests/fixtures/real/*."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx

from gazzetta_mcp.cache.sqlite import SqliteCache
from gazzetta_mcp.config import Settings
from gazzetta_mcp.parsing import GuParser
from gazzetta_mcp.service import GazzettaService, Limits
from gazzetta_mcp.sources.gu import GuClient
from gazzetta_mcp.sources.normattiva import NormattivaLinkBuilder
from gazzetta_mcp.sources.ratelimit import RateLimiter

FIX = Path(__file__).parent.parent / "fixtures" / "real"
TODAY = date(2026, 10, 5)

ROUTES = {
    "/rss/SG": "rss_SG.xml",
    "/rss/S4": "rss_S4.xml",
    "/eli/gu/2026/10/03/230/SG/html": "sommario_sg_2026-10-03_230.html",
    "/eli/gu/2026/10/02/76/S4/html": "sommario_s4_2026-10-02_76.html",
    "/eli/id/2026/10/03/26A05182/SG": "atto_scheda_26A05182_sg.html",
    "/eli/id/2026/10/02/26E05478/S4": "atto_scheda_26E05478_s4.html",
    "/atto/serie_generale/caricaArticoloDefault/originario": "atto_testo_26A05182_sg.html",
}


class NoLimit(RateLimiter):
    def __init__(self) -> None:
        super().__init__(1000.0)

    async def acquire(self) -> None:
        return None


def make_service(
    limits: Limits | None = None, cache: SqliteCache | None = None
) -> tuple[GazzettaService, list[httpx.Request], SqliteCache, GuClient]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        name = ROUTES.get(request.url.path)
        if name is None:
            return httpx.Response(404, text="not found")
        return httpx.Response(200, content=(FIX / name).read_bytes())

    settings = Settings()
    cache = cache or SqliteCache(":memory:")
    client = GuClient(
        settings, cache=cache, transport=httpx.MockTransport(handler), limiter=NoLimit()
    )
    service = GazzettaService(
        client=client,
        parser=GuParser(),
        cache=cache,
        linker=NormattivaLinkBuilder(settings),
        settings=settings,
        limits=limits,
        today=lambda: TODAY,
        closers=(client.aclose, cache.close),
    )
    return service, seen, cache, client
