from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from gazzetta_mcp.cache.sqlite import SqliteCache
from gazzetta_mcp.config import Settings
from gazzetta_mcp.models import SearchFilters
from gazzetta_mcp.sources.archivio import ArchivioClient, search_words
from gazzetta_mcp.sources.gu import GuHttpError

from ._service_helpers import NoLimit, make_service

FIXTURE = Path(__file__).parent.parent / "fixtures" / "archivio"
SAMPLE = (FIXTURE / "ricerca_avanzata_incentivi_veicoli.json").read_bytes()


def make_client(status: int = 200, cache=None):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, content=SAMPLE if status == 200 else b"boom")

    client = ArchivioClient(
        Settings(), cache=cache, transport=httpx.MockTransport(handler), limiter=NoLimit()
    )
    return client, seen


def test_search_words_drop_stopwords():
    assert search_words("incentivi per l'acquisto di autoveicoli") == [
        "incentivi",
        "acquisto",
        "autoveicoli",
    ]
    assert search_words("di la") == ["di", "la"]


async def test_cerca_posts_one_request_and_ranks_by_matched_words():
    client, seen = make_client()
    hits, total = await client.cerca("incentivi veicoli", SearchFilters(limite=10))
    assert len(seen) == 1 and seen[0].method == "POST"
    body = json.loads(seen[0].content)
    assert body["titoloRicerca"] == "incentivi veicoli" and body["orderType"] == "recente"
    assert total == 258 and len(hits) == 5
    assert all(h.origine == "normattiva" and h.serie.value == "SG" for h in hits)
    h = hits[0]
    assert h.link == f"https://www.gazzettaufficiale.it/eli/id/{h.data:%Y/%m/%d}/{h.codice}/SG"
    scores = [x.punteggio for x in hits]
    assert scores == sorted(scores, reverse=True)


async def test_cerca_sends_filters_and_uses_the_cache():
    from datetime import date

    cache = SqliteCache(":memory:")
    client, seen = make_client(cache=cache)
    f = SearchFilters(tipo="decreto", dal=date(2026, 1, 1), al=date(2026, 12, 31), limite=3)
    first, _ = await client.cerca("incentivi", f)
    body = json.loads(seen[0].content)
    assert body["denominazioneAtto"] == "DECRETO"
    assert body["dataInizioPubProvvedimento"] == "2026-01-01"
    assert body["dataFinePubProvvedimento"] == "2026-12-31"
    assert len(first) == 3
    second, _ = await client.cerca("incentivi", f)
    assert len(seen) == 1 and [h.codice for h in second] == [h.codice for h in first]


async def test_cerca_http_error_and_empty_query():
    client, seen = make_client(status=500)
    with pytest.raises(GuHttpError):
        await client.cerca("incentivi", SearchFilters())
    assert await client.cerca("   ", SearchFilters()) == ([], 0)
    assert len(seen) == 1


async def test_service_merges_archive_hits_after_local_ones():
    service, seen, cache, _ = make_service()
    client, archive_seen = make_client()
    service._archivio = client
    r = await service.cerca("incentivi veicoli")
    assert len(archive_seen) == 1
    origins = [x["origine"] for x in r["risultati"]]
    assert "normattiva" in origins
    assert "archivio" in r["copertura"] and "leggi_atto" in r["copertura"]
    codes = [x["codice"] for x in r["risultati"]]
    assert len(codes) == len(set(codes))
    # no network at all with aggiorna=false
    await service.cerca("incentivi veicoli", aggiorna=False)
    assert len(archive_seen) == 1


async def test_service_archive_failure_is_only_a_note():
    service, *_ = make_service()
    client, _ = make_client(status=500)
    service._archivio = client
    r = await service.cerca("decreto")
    assert any("archivio non riuscita" in n for n in r["note"])
    assert r["totale"] > 0
