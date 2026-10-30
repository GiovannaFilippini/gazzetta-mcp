"""One rate limiter for every client that talks to Normattiva (no network).

The archive search and ``testo_vigente`` hit the same site: together they must stay at one
request per interval, not one each.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx
from fastmcp import Client, FastMCP

from gazzetta_mcp.config import Settings
from gazzetta_mcp.models import SearchFilters
from gazzetta_mcp.service import build_service
from gazzetta_mcp.tools.vigente import register_vigente

FIX = Path(__file__).parent.parent / "fixtures" / "vigente"
PRIMO = (FIX / "dettaglio_legge_1990_241_primo_articolo.json").read_bytes()

RPS = 10.0  # 0.1 s between requests: fast test, clear margin over timer jitter


def _recording_transport(times: list[float]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        times.append(time.monotonic())
        if request.url.path.endswith("/ricerca/avanzata"):
            return httpx.Response(200, content=json.dumps({"listaAtti": []}).encode())
        return httpx.Response(200, content=PRIMO)

    return httpx.MockTransport(handler)


async def test_archive_search_and_testo_vigente_share_one_limiter(tmp_path):
    settings = Settings(requests_per_second=RPS, cache_path=str(tmp_path / "cache.sqlite"))
    service = build_service(settings)
    times: list[float] = []
    transport = _recording_transport(times)
    # Same client as the real wiring, only the network is swapped for the recorder.
    service._archivio._http = httpx.AsyncClient(transport=transport)
    mcp = FastMCP("test")
    register_vigente(mcp, lambda: service, transport=transport)

    async def vigente(atto: str):
        async with Client(mcp) as c:
            await c.call_tool("testo_vigente", {"atto": atto})

    try:
        await asyncio.gather(
            service._archivio.cerca("appalti", SearchFilters()),
            vigente("legge 241 del 1990"),
            vigente("legge 241 del 1990 art. 2"),
        )
    finally:
        await service.aclose()

    assert len(times) >= 3
    gaps = [b - a for a, b in zip(sorted(times), sorted(times)[1:])]
    assert min(gaps) >= (1 / RPS) * 0.75, gaps  # timer jitter on Windows is about 15 ms
