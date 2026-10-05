from __future__ import annotations

from datetime import date

import httpx
import pytest

from gazzetta_mcp.cache.sqlite import SqliteCache
from gazzetta_mcp.models import Serie
from gazzetta_mcp.parsing import GuParser, parse_elenco_30giorni
from gazzetta_mcp.sources.gu import GuClient, UnsupportedSerieError

from ._service_helpers import FIX, NoLimit


def test_parse_s4_elenco_newest_first_without_duplicates():
    issues = parse_elenco_30giorni((FIX / "elenco_30giorni_concorsi.html").read_bytes())
    assert issues[0] == (date(2026, 10, 2), 76)
    assert issues[-1] == (date(2026, 9, 8), 69)
    assert len(issues) == 8 == len(set(issues))
    assert [d for d, _ in issues] == sorted((d for d, _ in issues), reverse=True)
    assert [n for _, n in issues] == list(range(76, 68, -1))


def test_parse_sg_elenco():
    issues = parse_elenco_30giorni((FIX / "elenco_30giorni_serie_generale.html").read_bytes())
    assert issues[0] == (date(2026, 10, 3), 230)
    assert len(issues) >= 20 and len(issues) == len(set(issues))


def test_parse_both_link_styles_and_entities():
    raw = (
        b'<a href="/x?dataPubblicazioneGazzetta=2026-09-08&amp;numeroGazzetta=69">a</a>'
        b'<a href="/y?dataPubblicazioneGazzetta=20260908&numeroGazzetta=69">b</a>'
        b'<a href="/z?dataPubblicazioneGazzetta=2026-09-11&numeroGazzetta=70&x=1">c</a>'
    )
    assert parse_elenco_30giorni(raw) == [(date(2026, 9, 11), 70), (date(2026, 9, 8), 69)]


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"   ",
        b"<html><body>nothing here</body></html>",
        b"dataPubblicazioneGazzetta=2026-13-45&numeroGazzetta=3",  # impossible date
    ],
)
def test_parse_garbage_gives_empty_list(raw):
    assert parse_elenco_30giorni(raw) == []


def test_parser_object_exposes_it():
    raw = (FIX / "elenco_30giorni_concorsi.html").read_bytes()
    assert GuParser().parse_elenco_30giorni(raw) == parse_elenco_30giorni(raw)


def make_client(cache=None):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        name = {
            "/30giorni/concorsi": "elenco_30giorni_concorsi.html",
            "/30giorni/serie_generale": "elenco_30giorni_serie_generale.html",
        }.get(request.url.path)
        if name is None:
            return httpx.Response(404)
        return httpx.Response(200, content=(FIX / name).read_bytes())

    client = GuClient(cache=cache, transport=httpx.MockTransport(handler), limiter=NoLimit())
    return client, seen


async def test_client_fetches_elenco_for_sg_and_s4_and_caches():
    cache = SqliteCache(":memory:")
    client, seen = make_client(cache)
    assert client.url_elenco_30giorni(Serie.S4).endswith("/30giorni/concorsi")
    first = await client.get_elenco_30giorni(Serie.S4)
    again = await client.get_elenco_30giorni(Serie.S4)
    await client.get_elenco_30giorni(Serie.SG)
    assert not first.from_cache and again.from_cache
    assert [r.url.path for r in seen] == ["/30giorni/concorsi", "/30giorni/serie_generale"]
    assert seen[0].headers["user-agent"].startswith("gazzetta-mcp/")
    await client.aclose()


@pytest.mark.parametrize("serie", [Serie.S1, Serie.S2, Serie.S3, Serie.S5, Serie.P2])
async def test_client_unsupported_serie(serie):
    client, seen = make_client()
    with pytest.raises(UnsupportedSerieError):
        await client.get_elenco_30giorni(serie)
    assert seen == []
    await client.aclose()
