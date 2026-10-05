from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from gazzetta_mcp.config import Settings
from gazzetta_mcp.models import SearchFilters
from gazzetta_mcp.parsing.ricerca import parse_ricerca
from gazzetta_mcp.sources.gu import GuHttpError
from gazzetta_mcp.sources.ricerca_gu import RicercaGuClient

from ._service_helpers import NoLimit, make_service

SAMPLE = (
    Path(__file__).parent.parent / "fixtures" / "archivio" / "ricerca_gu_incentivi_autoveicoli.html"
).read_bytes()
BASE = "https://www.gazzettaufficiale.it"


def test_parse_ricerca_fixture():
    hits, total = parse_ricerca(SAMPLE, BASE)
    assert total >= len(hits) == 2
    h = next(x for x in hits if x.codice == "24G00229")
    assert h.data.isoformat() == "2024-12-31" and h.origine == "ricerca_gu"
    assert h.titolo.startswith("LEGGE 30 dicembre 2024, n. 207: Bilancio di previsione")
    assert "(24G00229)" not in h.titolo and "  " not in h.titolo
    assert "Suppl. Ordinario n. 43" in h.estratto and "GU n.305" in h.estratto
    assert h.link == f"{BASE}/eli/id/2024/12/31/24G00229/SG"
    assert parse_ricerca(b"", BASE) == ([], 0)
    assert parse_ricerca(b"<html><body>niente</body></html>", BASE) == ([], 0)


def make_client(status: int = 200):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, text="form", headers={"set-cookie": "TS=1; Path=/"})
        return httpx.Response(status, content=SAMPLE if status == 200 else b"boom")

    client = RicercaGuClient(Settings(), transport=httpx.MockTransport(handler), limiter=NoLimit())
    return client, seen


async def test_cerca_gets_the_form_then_posts_once():
    client, seen = make_client()
    hits, total, _ = await client.cerca("incentivi per l'acquisto di autoveicoli", SearchFilters())
    assert [r.method for r in seen] == ["GET", "POST"]
    assert seen[1].url.path == "/do/ricerca/atto/serie_generale/originario/0"
    assert "TS=1" in seen[1].headers.get("cookie", "")
    form = parse_qs(seen[1].content.decode())
    assert form["testo"] == ["incentivi acquisto autoveicoli"]
    assert form["tipoRicercaTesto"] == ["ALL_WORDS"] and form["annoPubblicazioneDa"] == ["1988"]
    assert len(hits) == 2 and total >= 2


async def test_cerca_errors_and_empty_query():
    client, _ = make_client(status=500)
    with pytest.raises(GuHttpError):
        await client.cerca("incentivi", SearchFilters())
    assert tuple(await client.cerca("  ", SearchFilters())) == ([], 0, [])


async def test_service_uses_it_only_when_wired():
    service, *_ = make_service()
    client, seen = make_client()
    r = await service.cerca("bilancio previsione")
    assert not seen and all(x["origine"] != "ricerca_gu" for x in r["risultati"])
    service._ricerca_gu = client
    r = await service.cerca("bilancio previsione")
    assert [q.method for q in seen] == ["GET", "POST"]
    assert any(x["origine"] == "ricerca_gu" for x in r["risultati"])
    assert "ricerca avanzata" in r["copertura"]


def test_switched_off_by_default(monkeypatch):
    monkeypatch.delenv("GAZZETTA_MCP_RICERCA_GU", raising=False)
    assert Settings.from_env().ricerca_gu is False
    monkeypatch.setenv("GAZZETTA_MCP_RICERCA_GU", "1")
    assert Settings.from_env().ricerca_gu is True
