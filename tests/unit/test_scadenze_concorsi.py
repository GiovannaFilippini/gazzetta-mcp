from __future__ import annotations

from datetime import date

import httpx
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from gazzetta_mcp.cache.sqlite import SqliteCache
from gazzetta_mcp.config import Settings
from gazzetta_mcp.models import DISCLAIMER
from gazzetta_mcp.parsing import GuParser
from gazzetta_mcp.scadenze_concorsi import MAX_LETTURE
from gazzetta_mcp.service import GazzettaService, Limits
from gazzetta_mcp.sources.gu import GuClient
from gazzetta_mcp.sources.normattiva import NormattivaLinkBuilder
from gazzetta_mcp.tools.scadenze import register_scadenze

from ._service_helpers import FIX, NoLimit

SCAD = FIX.parent / "scadenze"
OGGI = date(2026, 10, 28)  # the issue of 2 October is 26 days old: inside the 30-day window


def _testo(codice: str) -> bytes:
    """The real text if saved, otherwise a real text without a deadline (the Bocconi call)."""
    name = SCAD / f"testo_{codice}.html"
    return (name if name.exists() else SCAD / "testo_26E05295.html").read_bytes()


def make(fail_texts: bool = False):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/30giorni/concorsi":
            return httpx.Response(200, content=(FIX / "elenco_30giorni_concorsi.html").read_bytes())
        if path.endswith("/S4/html"):
            return httpx.Response(
                200, content=(FIX / "sommario_s4_2026-10-02_76.html").read_bytes()
            )
        if path.startswith("/eli/id/") and path.endswith("/S4"):
            if fail_texts:
                return httpx.Response(500, text="error")
            return httpx.Response(200, content=(FIX / "atto_scheda_26E05478_s4.html").read_bytes())
        if path.startswith("/atto/concorsi/caricaArticoloDefault"):
            codice = request.url.params["atto.codiceRedazionale"]
            return httpx.Response(200, content=_testo(codice))
        return httpx.Response(404, text="not found")  # includes the article menu: single text page

    settings = Settings()
    cache = SqliteCache(":memory:")
    client = GuClient(
        settings, cache=cache, transport=httpx.MockTransport(handler), limiter=NoLimit()
    )
    service = GazzettaService(
        client=client,
        parser=GuParser(),
        cache=cache,
        linker=NormattivaLinkBuilder(settings),
        settings=settings,
        limits=Limits(recent_issues_s4=1),
        today=lambda: OGGI,
        closers=(client.aclose, cache.close),
    )
    return service, seen


@pytest.fixture
def service():
    return make()[0]


async def call(service, **args):
    mcp = FastMCP("test")
    register_scadenze(mcp, lambda: service)
    async with Client(mcp) as c:
        return (await c.call_tool("scadenze_concorsi", args)).data


async def test_tool_registered_with_the_agreed_signature(service):
    mcp = FastMCP("test")
    register_scadenze(mcp, lambda: service)
    async with Client(mcp) as c:
        tools = {t.name: t for t in await c.list_tools()}
    assert set(tools) == {"scadenze_concorsi"}
    props = tools["scadenze_concorsi"].input_schema["properties"]
    assert set(props) == {"parole_chiave", "regione", "entro_giorni", "limite"}
    assert props["entro_giorni"]["default"] == 7 and props["limite"]["default"] == 10


async def test_closing_this_week_with_keywords(service):
    data = await call(service, parole_chiave="infermiere")
    assert data["avvertenza"] == DISCLAIMER
    assert data["fonte"] and all(u.startswith("http") for u in data["fonte"])
    assert data["totale"] == 1
    r = data["risultati"][0]
    assert r["codice"] == "26E05265"
    assert r["scadenza"] == "2026-11-02"  # 1 November is a Sunday and All Saints
    assert r["giorni_mancanti"] == 5
    assert r["scadenza_ricavata_da"] == "giorni_dalla_pubblicazione"
    assert "Ognissanti" in r["come"]
    assert r["link"].startswith("http") and r["data_gu"] == "2026-10-02" and r["posti"] == 20
    # the second match (a nursing manager) has a text without deadline
    assert data["testi_letti"] == 2 and data["testi_non_letti"] == 0
    assert data["senza_scadenza"] == 1
    assert "verifica sempre" in data["avviso_scadenza"]
    assert "Testi letti: 2" in data["copertura"]


async def test_region_filter(service):
    data = await call(service, parole_chiave="infermiere", regione="Lombardia")
    assert data["regione"] == "Lombardia"
    assert [r["codice"] for r in data["risultati"]] == ["26E05265"]
    assert data["risultati"][0]["regione"] == "Lombardia"
    altra = await call(service, parole_chiave="infermiere", regione="Lazio")
    assert altra["totale"] == 0 and altra["bandi_candidati"] == 0


async def test_results_are_ordered_by_date_and_limited():
    service, _ = make()
    data = await call(service, parole_chiave="concorso", entro_giorni=40, limite=2)
    dates = [r["scadenza"] for r in data["risultati"]]
    assert dates == sorted(dates)
    assert data["mostrati"] == len(data["risultati"]) <= 2


async def test_reading_is_capped_and_reported(service):
    data = await call(service)  # no keywords: every call of the issue is a candidate
    assert data["testi_letti"] == MAX_LETTURE
    assert data["testi_non_letti"] == data["bandi_candidati"] - MAX_LETTURE > 0
    assert any("tetto" in n for n in data["note"])
    assert data["senza_scadenza"] > 0  # the filler text has no deadline
    # a second call goes on: texts already in the cache are free
    again = await call(service)
    assert again["testi_letti"] > data["testi_letti"]


async def test_cached_texts_do_not_use_the_cap():
    service, seen = make()
    await call(service, parole_chiave="infermiere")
    before = len(seen)
    await call(service, parole_chiave="infermiere")
    texts = [r for r in seen[before:] if r.url.path.startswith("/atto/")]
    assert texts == []


async def test_deadline_not_found_is_never_invented(service):
    data = await call(service, parole_chiave="assistant professor")
    assert data["totale"] == 0
    assert data["senza_scadenza"] == 1
    voce = data["senza_scadenza_rilevata"][0]
    assert voce["codice"] == "26E05295" and voce["scadenza"] is None
    assert voce["come"] == "scadenza non rilevata, controlla il bando"
    assert voce["scadenza_ricavata_da"] == "non_rilevata"


async def test_window_and_already_expired(service):
    stretta = await call(service, parole_chiave="infermiere", entro_giorni=2)
    assert stretta["totale"] == 0 and stretta["oltre_la_finestra"] == 1
    scaduto = await call(service, parole_chiave="dottorato")
    assert scaduto["totale"] == 0 and scaduto["gia_scaduti"] == 1  # explicit date 12 October


async def test_short_term_formula():
    service, _ = make()
    data = await call(service, parole_chiave="borsa", entro_giorni=60)
    assert data["risultati"] == []  # CNR 15 days: already expired on 28 October
    assert data["gia_scaduti"] >= 1


async def test_failing_texts_are_reported_not_hidden():
    service, _ = make(fail_texts=True)
    data = await call(service, parole_chiave="infermiere")
    assert data["totale"] == 0 and data["testi_letti"] == 0
    assert data["senza_scadenza"] == 2
    assert any("non si sono potuti leggere" in n for n in data["note"])


async def test_input_errors_are_italian_tool_errors(service):
    with pytest.raises(ToolError, match="negativo"):
        await call(service, entro_giorni=-1)
    with pytest.raises(ToolError, match="Regione"):
        await call(service, regione="Atlantide")
