from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from gazzetta_mcp.cache.sqlite import SqliteCache
from gazzetta_mcp.config import Settings
from gazzetta_mcp.models import SearchFilters
from gazzetta_mcp.searchtext import search_words
from gazzetta_mcp.sources.archivio import ArchivioClient
from gazzetta_mcp.sources.gu import GuHttpError

from ._service_helpers import NoLimit, make_service

FIXTURE = Path(__file__).parent.parent / "fixtures" / "archivio"
SAMPLE = (FIXTURE / "ricerca_avanzata_incentivi_veicoli.json").read_bytes()
REPEALED_CODE = "26G00156"  # one of the acts in the sample


TODAY = date(2026, 10, 5)


def make_client(status: int = 200, cache=None, repealed_status: int = 200):
    """Mock of the Normattiva API: class 3 (repealed) answers with one act of the sample."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        if body.get("classeProvvedimento") == "3":
            if repealed_status != 200:
                return httpx.Response(repealed_status, content=b"boom")
            atto = next(
                a
                for a in json.loads(SAMPLE)["listaAtti"]
                if a["codiceRedazionale"] == REPEALED_CODE
            )
            return httpx.Response(200, json={"listaAtti": [atto], "numeroAttiTrovati": 1})
        return httpx.Response(status, content=SAMPLE if status == 200 else b"boom")

    client = ArchivioClient(
        Settings(),
        cache=cache,
        transport=httpx.MockTransport(handler),
        limiter=NoLimit(),
        today=lambda: TODAY,
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
    hits, total, note = await client.cerca("incentivi veicoli", SearchFilters(limite=10))
    assert len(seen) == 1 and seen[0].method == "POST" and note == []
    body = json.loads(seen[0].content)
    assert body["titoloRicerca"] == "incentivi veicoli" and body["orderType"] == "recente"
    assert total == 258 and len(hits) == 5
    assert all(h.origine == "normattiva" and h.serie.value == "SG" for h in hits)
    h = hits[0]
    assert h.link == f"https://www.gazzettaufficiale.it/eli/id/{h.data:%Y/%m/%d}/{h.codice}/SG"
    scores = [x.punteggio for x in hits]
    assert scores == sorted(scores, reverse=True)


async def test_without_dal_the_period_is_the_last_year():
    client, seen = make_client()
    await client.cerca("incentivi", SearchFilters())
    assert json.loads(seen[0].content)["dataInizioPubProvvedimento"] == "2025-10-05"
    await client.cerca("incentivi", SearchFilters(dal=date(2024, 1, 1)))
    assert json.loads(seen[1].content)["dataInizioPubProvvedimento"] == "2024-01-01"


async def test_solo_vigenti_leaves_out_repealed_acts():
    client, seen = make_client()
    everything, *_ = await client.cerca("incentivi veicoli", SearchFilters(limite=50))
    seen.clear()
    hits, total, note = await client.cerca(
        "incentivi veicoli", SearchFilters(limite=50, solo_vigenti=True)
    )
    classes = [json.loads(r.content).get("classeProvvedimento") for r in seen]
    assert sorted(map(str, classes)) == ["3", "None"]
    assert REPEALED_CODE in {h.codice for h in everything}
    assert REPEALED_CODE not in {h.codice for h in hits}
    assert len(hits) == len(everything) - 1 and total == 258
    assert note == ["Esclusi 1 atti abrogati."]


async def test_repealed_check_failure_keeps_hits_and_says_so():
    client, _ = make_client(repealed_status=500)
    hits, _total, note = await client.cerca("incentivi", SearchFilters(solo_vigenti=True))
    assert len(hits) == 5 and REPEALED_CODE in {h.codice for h in hits}
    assert any("abrogati" in n and "non sono riuscito" in n.lower() for n in note)


async def test_cerca_sends_filters_and_uses_the_cache():
    cache = SqliteCache(":memory:")
    client, seen = make_client(cache=cache)
    f = SearchFilters(tipo="decreto", dal=date(2026, 1, 1), al=date(2026, 12, 31), limite=3)
    first, *_ = await client.cerca("incentivi", f)
    body = json.loads(seen[0].content)
    assert body["denominazioneAtto"] == "DECRETO"
    assert body["dataInizioPubProvvedimento"] == "2026-01-01"
    assert body["dataFinePubProvvedimento"] == "2026-12-31"
    assert len(first) == 3
    second, *_ = await client.cerca("incentivi", f)
    assert len(seen) == 1 and [h.codice for h in second] == [h.codice for h in first]


async def test_cerca_http_error_and_empty_query():
    client, seen = make_client(status=500)
    with pytest.raises(GuHttpError):
        await client.cerca("incentivi", SearchFilters())
    assert tuple(await client.cerca("   ", SearchFilters())) == ([], 0, [])
    assert len(seen) == 1


async def test_service_merges_archive_hits_after_local_ones():
    service, _seen, _cache, _ = make_service()
    client, archive_seen = make_client()
    service._archivio = client
    r = await service.cerca("incentivi veicoli")
    assert len(archive_seen) == 2  # search + repealed acts (solo_vigenti is the default)
    origins = [x["origine"] for x in r["risultati"]]
    assert "normattiva" in origins
    assert REPEALED_CODE not in [x["codice"] for x in r["risultati"]]
    assert "Esclusi 1 atti abrogati." in r["note"]
    assert "archivio" in r["copertura"] and "leggi_atto" in r["copertura"]
    codes = [x["codice"] for x in r["risultati"]]
    assert len(codes) == len(set(codes))
    # solo_vigenti=false: one request only and the repealed act comes back
    archive_seen.clear()
    r2 = await service.cerca("incentivi veicoli", solo_vigenti=False, limite=50)
    assert len(archive_seen) == 1
    assert REPEALED_CODE in [x["codice"] for x in r2["risultati"]]
    # no network at all with aggiorna=false
    archive_seen.clear()
    await service.cerca("incentivi veicoli", aggiorna=False)
    assert archive_seen == []


async def test_service_archive_failure_is_only_a_note():
    service, *_ = make_service()
    client, _ = make_client(status=500)
    service._archivio = client
    r = await service.cerca("decreto")
    assert any("archivio non riuscita" in n for n in r["note"])
    assert r["totale"] > 0
