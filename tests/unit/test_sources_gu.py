from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from gazzetta_mcp.config import Settings
from gazzetta_mcp.models import RawPage, Serie, Sommario
from gazzetta_mcp.sources.gu import (
    GuClient,
    GuHttpError,
    GuNotFoundError,
    NumeroNotFoundError,
    UnsupportedSerieError,
    parse_export_form,
    parse_feed_channel,
    resolve_numero,
    sommario_matches,
)
from gazzetta_mcp.sources.ratelimit import RateLimiter

FIX = Path(__file__).parent.parent / "fixtures" / "real"
BASE = "https://www.gazzettaufficiale.it"


def fixture(name: str) -> bytes:
    return (FIX / name).read_bytes()


async def no_wait() -> None:
    return None


class NoLimit(RateLimiter):
    def __init__(self) -> None:
        super().__init__(1000.0)

    async def acquire(self) -> None:
        return None


def make_client(handler, cache=None, settings=None) -> tuple[GuClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = GuClient(
        settings or Settings(),
        cache=cache,
        transport=httpx.MockTransport(wrapped),
        limiter=NoLimit(),
    )
    return client, seen


class FakeCache:
    def __init__(self) -> None:
        self.http: dict[str, RawPage] = {}
        self.sommari: dict[tuple[date, Serie], Sommario] = {}

    def get_http(self, url, max_age_seconds):
        return self.http.get(url)

    def put_http(self, page):
        self.http[page.url] = page

    def get_sommario(self, data, serie):
        return self.sommari.get((data, serie))


D = date(2026, 10, 3)


def test_url_builders():
    c = GuClient(Settings())
    assert c.url_sommario(D, Serie.SG, 230) == f"{BASE}/eli/gu/2026/10/03/230/SG/html"
    assert c.url_pdf(D, Serie.SG, 230) == f"{BASE}/eli/gu/2026/10/03/230/SG/pdf"
    assert c.url_atto("26A05182", D, Serie.SG) == f"{BASE}/eli/id/2026/10/03/26A05182/SG"
    assert c.url_feed(Serie.S4) == f"{BASE}/rss/S4"
    assert c.url_atto_testo("26A05182", D, Serie.SG, "DECRETO") == (
        f"{BASE}/atto/serie_generale/caricaArticoloDefault/originario"
        "?atto.dataPubblicazioneGazzetta=2026-10-03&atto.codiceRedazionale=26A05182"
        "&atto.tipoProvvedimento=DECRETO"
    )
    assert "concorsi/" in c.url_atto_testo("26E05478", D, Serie.S4, "AVVISO")
    assert "tipoProvvedimento=LEGGE%20REGIONALE" in c.url_atto_testo(
        "26R00269", D, Serie.S3, "LEGGE REGIONALE"
    )
    assert "tipoProvvedimento" not in c.url_atto_testo("26A05182", D, Serie.SG, None)


def test_base_url_from_settings():
    c = GuClient(Settings(gu_base_url="http://localhost:9"))
    assert c.url_feed(Serie.SG) == "http://localhost:9/rss/SG"


def test_unsupported_serie():
    with pytest.raises(UnsupportedSerieError):
        GuClient(Settings()).url_atto_testo("X", D, Serie.P2, None)


async def test_get_feed_sends_user_agent_and_returns_content():
    def handler(request):
        return httpx.Response(
            200, content=fixture("rss_SG.xml"), headers={"content-type": "application/rss+xml"}
        )

    settings = Settings(user_agent="test-agent/1")
    client, seen = make_client(handler, settings=settings)
    page = await client.get_feed(Serie.SG)
    assert str(seen[0].url) == f"{BASE}/rss/SG"
    assert seen[0].headers["user-agent"] == "test-agent/1"
    assert page.content == fixture("rss_SG.xml")
    assert page.content_type == "application/rss+xml"
    assert not page.from_cache
    await client.aclose()


async def test_all_fetch_methods_hit_expected_urls():
    client, seen = make_client(lambda r: httpx.Response(200, content=b"x"))
    await client.get_sommario(D, Serie.SG, 230)
    await client.get_atto_scheda("26A05182", D, Serie.SG)
    await client.get_atto_testo("26A05182", D, Serie.SG, "DECRETO")
    assert [r.url.path for r in seen] == [
        "/eli/gu/2026/10/03/230/SG/html",
        "/eli/id/2026/10/03/26A05182/SG",
        "/atto/vediMenuHTML",
        "/atto/serie_generale/caricaArticoloDefault/originario",
    ]
    assert seen[2].url.params["atto.codiceRedazionale"] == "26A05182"
    assert seen[2].url.params["tipoSerie"] == "serie_generale"
    assert seen[3].url.params["atto.tipoProvvedimento"] == "DECRETO"


def test_parse_export_form_fixtures():
    action, fields = parse_export_form(fixture("atto_menu_26A05182_sg.html"))
    assert action == "/atto/stampa/serie_generale/originario"
    articles = [v for k, v in fields if k == "articoliSelected"]
    assert len(articles) == 3  # Art. 1, Art. 2 and Allegato 1
    assert "art.flagTipoArticolo=1" in articles[2]
    assert "&amp;" not in articles[0]
    assert ("codiceRedazionale", "26A05182") in fields
    assert ("dataPubblicazioneGazzetta", "2026-10-03") in fields
    assert parse_export_form(fixture("atto_menu_26A05144_sg.html")) is None
    assert parse_export_form(b"") is None


async def test_atto_testo_with_menu_posts_the_export_form():
    def handler(request):
        if request.url.path == "/atto/vediMenuHTML":
            return httpx.Response(200, content=fixture("atto_menu_26A05182_sg.html"))
        return httpx.Response(200, content=fixture("atto_stampa_26A05182_sg.html"))

    cache = FakeCache()
    client, seen = make_client(handler, cache=cache)
    page = await client.get_atto_testo("26A05182", D, Serie.SG, "DECRETO")
    assert [(r.method, r.url.path) for r in seen] == [
        ("GET", "/atto/vediMenuHTML"),
        ("POST", "/atto/stampa/serie_generale/originario"),
    ]
    assert seen[1].headers["content-type"] == "application/x-www-form-urlencoded"
    assert seen[1].content.count(b"articoliSelected=") == 3
    assert page.content == fixture("atto_stampa_26A05182_sg.html")
    # the export URL is shared by every act: the cache key must name the act
    assert "codiceRedazionale=26A05182" in page.url
    again = await client.get_atto_testo("26A05182", D, Serie.SG, "DECRETO")
    assert again.from_cache and len(seen) == 2
    await client.aclose()


async def test_atto_testo_without_menu_uses_single_page():
    def handler(request):
        if request.url.path == "/atto/vediMenuHTML":
            return httpx.Response(200, content=fixture("atto_menu_26A05144_sg.html"))
        return httpx.Response(200, content=fixture("atto_testo_26A05144_sg.html"))

    client, seen = make_client(handler)
    page = await client.get_atto_testo("26A05144", D, Serie.SG, "COMUNICATO")
    assert [r.url.path for r in seen] == [
        "/atto/vediMenuHTML",
        "/atto/serie_generale/caricaArticoloDefault/originario",
    ]
    assert page.content == fixture("atto_testo_26A05144_sg.html")
    await client.aclose()


async def test_atto_testo_menu_not_found_falls_back():
    def handler(request):
        if request.url.path == "/atto/vediMenuHTML":
            return httpx.Response(404)
        return httpx.Response(200, content=b"<pre>x</pre>")

    client, seen = make_client(handler)
    page = await client.get_atto_testo("26A05182", D, Serie.SG, None)
    assert page.content == b"<pre>x</pre>"
    assert len(seen) == 2
    await client.aclose()


async def test_not_found_and_http_errors():
    client, _ = make_client(lambda r: httpx.Response(404))
    with pytest.raises(GuNotFoundError):
        await client.get_feed(Serie.SG)
    client, _ = make_client(lambda r: httpx.Response(503))
    with pytest.raises(GuHttpError):
        await client.get_feed(Serie.SG)

    def boom(request):
        raise httpx.ConnectError("down")

    client, _ = make_client(boom)
    with pytest.raises(GuHttpError):
        await client.get_feed(Serie.SG)


async def test_http_cache_roundtrip():
    cache = FakeCache()
    client, seen = make_client(lambda r: httpx.Response(200, content=b"hello"), cache=cache)
    first = await client.get_feed(Serie.SG)
    second = await client.get_feed(Serie.SG)
    assert len(seen) == 1
    assert not first.from_cache
    assert second.from_cache
    assert second.content == b"hello"
    assert f"{BASE}/rss/SG" in cache.http


async def test_cache_hit_skips_rate_limiter():
    cache = FakeCache()
    url = f"{BASE}/rss/SG"
    cache.put_http(RawPage(url, b"c", "text/xml", datetime.now(timezone.utc)))

    class Boom(NoLimit):
        async def acquire(self):
            raise AssertionError("limiter must not be used on cache hit")

    client = GuClient(
        Settings(), cache=cache, transport=httpx.MockTransport(lambda r: 1 / 0), limiter=Boom()
    )
    assert (await client.get_feed(Serie.SG)).from_cache


# --- number resolution --------------------------------------------------------------


def test_parse_feed_channel_fixtures():
    assert parse_feed_channel(fixture("rss_SG.xml")) == (date(2026, 10, 3), 230)
    assert parse_feed_channel(fixture("rss_S4.xml"))[1] == 76
    assert parse_feed_channel(fixture("rss_S1.xml")) == (date(2026, 9, 30), 39)
    assert parse_feed_channel(b"<rss><channel><link>http://x/y</link></channel></rss>") is None


def test_sommario_matches_fixtures():
    sg = fixture("sommario_sg_2026-10-03_230.html")
    assert sommario_matches(sg, D, 230)
    assert not sommario_matches(sg, D, 229)
    assert not sommario_matches(sg, date(2026, 10, 2), 230)
    assert sommario_matches(fixture("sommario_s4_2026-10-02_76.html"), date(2026, 10, 2), 76)


def page_for(numero: int, data: date) -> bytes:
    return (
        f'<a href="/gu/vediPermalink?dataPubblicazioneGazzetta={data.isoformat()}'
        f'&amp;numeroGazzetta={numero}&amp;tipoSerie=serie_generale">'
    ).encode()


def stub_page() -> bytes:
    return b'<a href="/x/vediPermalink?dataPubblicazioneGazzetta=2022-03-01&numeroGazzetta=50">'


def resolver_handler(true_numero: int, data: date):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rss/SG":
            return httpx.Response(200, content=fixture("rss_SG.xml"))
        parts = request.url.path.split("/")  # ['', 'eli', 'gu', Y, M, D, NUM, SERIE, 'html']
        if parts[:3] == ["", "eli", "gu"]:
            n = int(parts[6])
            body = page_for(n, data) if n == true_numero else stub_page()
            return httpx.Response(200, content=body)
        return httpx.Response(404)

    return handler


async def test_resolve_from_cache_makes_no_request():
    cache = FakeCache()
    cache.sommari[(D, Serie.SG)] = Sommario(Serie.SG, D, 230, "l", "p")
    client, seen = make_client(lambda r: httpx.Response(500))
    assert await resolve_numero(client, D, Serie.SG, cache=cache) == 230
    assert seen == []


async def test_resolve_latest_from_feed_single_request():
    client, seen = make_client(resolver_handler(230, D))
    assert await resolve_numero(client, D, Serie.SG) == 230
    assert len(seen) == 1


async def test_resolve_past_date_by_guessing_is_bounded():
    past = date(2026, 9, 25)  # 8 days before 2026-10-03: estimate 230 - 7 = 223
    client, seen = make_client(resolver_handler(222, past))
    assert await resolve_numero(client, past, Serie.SG) == 222
    assert 2 <= len(seen) <= 5

    client, seen = make_client(resolver_handler(10, past))
    with pytest.raises(NumeroNotFoundError):
        await resolve_numero(client, past, Serie.SG, max_guesses=3)
    assert len(seen) == 1 + 3


async def test_resolve_errors():
    client, _ = make_client(resolver_handler(230, D))
    with pytest.raises(NumeroNotFoundError):
        await resolve_numero(client, date(2026, 10, 10), Serie.SG)
    with pytest.raises(NumeroNotFoundError):
        await resolve_numero(client, date(2020, 1, 1), Serie.SG)
