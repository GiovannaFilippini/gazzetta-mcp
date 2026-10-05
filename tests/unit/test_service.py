from __future__ import annotations

import pytest

from gazzetta_mcp.models import DISCLAIMER
from gazzetta_mcp.service import Limits, ServiceError, user_message
from gazzetta_mcp.sources.gu import GuError, GuHttpError, NumeroNotFoundError

from ._service_helpers import make_service


def check(result: dict) -> None:
    assert result["avvertenza"] == DISCLAIMER
    assert result["fonte"] and all(u.startswith("http") for u in result["fonte"])


async def test_ultime_pubblicazioni_filters_by_days_and_uses_cache():
    service, seen, cache, _ = make_service()
    r = await service.ultime_pubblicazioni("SG", 7)
    check(r)
    assert r["totale"] > 0 and r["ultimo_numero"] == 230
    assert all(p["data"] >= "2026-09-28" for p in r["pubblicazioni"])
    assert cache.stats()["feed_items"] > 0
    n = len(seen)
    again = await service.ultime_pubblicazioni("SG", 7)
    assert again["dalla_cache"] and len(seen) == n


async def test_ultime_pubblicazioni_limits_output_and_days():
    service, *_ = make_service(Limits(max_feed_items=2))
    r = await service.ultime_pubblicazioni("SG", 30)
    assert r["mostrati"] == 2 and r["troncato"] is (r["totale"] > 2)
    old = await service.ultime_pubblicazioni("SG", 1)  # since 2026-10-04: nothing
    assert old["totale"] == 0
    with pytest.raises(ServiceError):
        await service.ultime_pubblicazioni("SG", 0)
    with pytest.raises(ServiceError, match="Serie"):
        await service.ultime_pubblicazioni("XX", 3)


async def test_sommario_resolves_number_and_caches():
    service, seen, _, _ = make_service()
    r = await service.sommario("2026-10-03", "SG")
    check(r)
    assert r["numero"] == 230 and r["link_pdf"].endswith("/230/SG/pdf")
    v = next(x for x in r["voci"] if x["codice"] == "26A05182")
    assert v["titolo"] and v["link"].endswith("/26A05182/SG")
    n = len(seen)
    again = await service.sommario("2026-10-03", "SG")
    assert again["dalla_cache"] and len(seen) == n


async def test_sommario_bad_input():
    service, *_ = make_service()
    with pytest.raises(ServiceError, match="AAAA-MM-GG"):
        await service.sommario("03/10/2026")
    with pytest.raises(NumeroNotFoundError):
        await service.sommario("2026-12-31", "SG")  # after the latest issue


async def test_leggi_atto_needs_date_then_works_after_feed():
    service, seen, cache, _ = make_service()
    with pytest.raises(ServiceError, match="ultime_pubblicazioni"):
        await service.leggi_atto("26A05182")
    await service.ultime_pubblicazioni("SG", 7)  # date now known from the cached feed
    r = await service.leggi_atto("26A05182")
    check(r)
    assert r["data"] == "2026-10-03" and r["serie"] == "SG"
    assert r["testo"] and r["tipo"] == "DECRETO" and not r["troncato"]
    assert r["link"].endswith("/eli/id/2026/10/03/26A05182/SG")
    n = len(seen)
    again = await service.leggi_atto("26a05182")
    assert again["dalla_cache"] and len(seen) == n
    assert cache.get_atto("26A05182") is not None


async def test_leggi_atto_date_known_from_sommario():
    service, *_ = make_service()
    await service.sommario("2026-10-03", "SG")
    r = await service.leggi_atto("26A05182")
    assert r["data"] == "2026-10-03"


async def test_leggi_atto_with_explicit_date_and_pagination():
    service, *_ = make_service(Limits(max_chars=500))
    first = await service.leggi_atto("26A05182", data="2026-10-03")
    assert first["troncato"] and first["prossimo_offset"] == 500
    assert "testo troncato" in first["testo"] and "offset=500" in first["testo"]
    second = await service.leggi_atto("26A05182", offset=first["prossimo_offset"])
    assert second["offset"] == 500 and second["testo"]
    with pytest.raises(ServiceError, match="offset"):
        await service.leggi_atto("26A05182", offset=10**9)


async def test_leggi_atto_s4_inferred_from_letter():
    service, seen, *_ = make_service()
    # The mock has no S4 text page: the scheda is fetched on S4, then the text request fails.
    with pytest.raises(GuError):
        await service.leggi_atto("26E05478", data="2026-10-02")
    assert any("/eli/id/2026/10/02/26E05478/S4" in str(r.url) for r in seen)


async def test_leggi_atto_errors():
    service, *_ = make_service()
    with pytest.raises(ServiceError, match="non e' valido"):
        await service.leggi_atto("bad code!")
    with pytest.raises(ServiceError, match="non trovato"):
        await service.leggi_atto("26A99999", data="2026-10-03")


async def test_cerca_concorsi_covers_only_cache_and_feed():
    service, seen, *_ = make_service()
    r = await service.cerca_concorsi("avviso")
    check(r)
    assert "SOLO" in r["copertura"] and r["totale"] > 0
    assert all(h["serie"] == "S4" for h in r["risultati"])
    assert [q.url.path for q in seen] == ["/rss/S4"]  # no crawling
    none = await service.cerca_concorsi("avviso", regione="Groenlandia")
    assert none["totale"] == 0
    with pytest.raises(ServiceError):
        await service.cerca_concorsi("  ")


async def test_rimando_normattiva():
    service, *_ = make_service()
    r = service.rimando_normattiva("legge 5 agosto 2026, n. 140")
    check(r)
    assert r["link_normattiva"].startswith("https://www.normattiva.it/uri-res/N2Ls?urn:nir")
    with pytest.raises(ValueError, match="Non riesco"):
        service.rimando_normattiva("boh")


async def test_cerca_empty_cache_then_results():
    service, *_ = make_service()
    empty = service.cerca("decreto")
    check(empty)
    assert empty["totale"] == 0 and "vuota" in empty["messaggio"]
    atto = await service.leggi_atto("26A05182", data="2026-10-03")
    word = atto["titolo"].split()[-1]
    r = service.cerca(word, serie="SG", dal="2026-10-01", al="2026-10-05", limite=5)
    check(r)
    assert any(h["codice"] == "26A05182" for h in r["risultati"])
    with pytest.raises(ServiceError, match="AAAA-MM-GG"):
        service.cerca("x", dal="ieri")


def test_user_message_never_leaks():
    assert "riprova" in user_message(GuHttpError("boom http://x"))
    assert user_message(RuntimeError("secret")) == "Errore interno imprevisto."


async def test_aclose_closes_resources():
    service, _, _, client = make_service()
    await service.aclose()
    assert client._http.is_closed
