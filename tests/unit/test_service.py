from __future__ import annotations

from datetime import date

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


async def test_leggi_atto_without_date_looks_up_the_latest_feed():
    service, seen, cache, _ = make_service()
    r = await service.leggi_atto("26A05182")  # date found in the SG feed, user never gives it
    check(r)
    assert r["data"] == "2026-10-03" and r["serie"] == "SG"
    assert r["testo"] and r["tipo"] == "DECRETO" and not r["troncato"]
    assert r["link"].endswith("/eli/id/2026/10/03/26A05182/SG")
    n = len(seen)
    again = await service.leggi_atto("26a05182")
    assert again["dalla_cache"] and len(seen) == n
    assert cache.get_atto("26A05182") is not None
    assert sum("/rss/" in str(r.url) for r in seen) == 1


async def test_leggi_atto_remembers_codes_seen_in_the_feed():
    service, seen, *_ = make_service()
    await service.ultime_pubblicazioni("SG", 7)
    n = len(seen)
    await service.leggi_atto("26A05182")
    assert not any("/rss/" in str(r.url) for r in seen[n:])  # no extra lookup


async def test_leggi_atto_unknown_date_gives_advice_after_bounded_lookups():
    service, seen, *_ = make_service()
    with pytest.raises(ServiceError, match="cerca"):
        await service.leggi_atto("26A99999")  # letter A -> only the SG feed is tried
    assert sum("/rss/" in str(r.url) for r in seen) == 1
    seen.clear()
    with pytest.raises(ServiceError, match="parola"):
        await service.leggi_atto("26X99999")  # unknown letter -> SG then S4, never more
    assert sum("/rss/" in str(r.url) for r in seen) <= 2


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
    with pytest.raises(ServiceError, match="non sembra valido"):
        await service.leggi_atto("bad code!")
    with pytest.raises(ServiceError, match="Non trovo l'atto"):
        await service.leggi_atto("26A99999", data="2026-10-03")


async def test_cerca_concorsi_cold_start_loads_recent_issues_within_the_cap():
    service, seen, cache, _ = make_service()
    r = await service.cerca_concorsi("infermiere", regione="lombardia")
    check(r)
    # 1 index + 8 issues listed by the index; nothing else, no crawling
    paths = [q.url.path for q in seen]
    assert paths[0] == "/30giorni/concorsi" and len(paths) == 9
    assert all(p.startswith("/eli/gu/") and p.endswith("/S4/html") for p in paths[1:])
    assert r["richieste_effettuate"] == 9
    assert cache.stats()["sommari"] == 8
    # coverage is always stated
    assert "dal 2026-09-08 al 2026-10-02" in r["copertura"]
    assert "bandi esaminati" in r["copertura"] and r["bandi_esaminati"] > 0
    assert "bando completo" in r["avviso_lettura"] and "sito ufficiale" in r["avviso_lettura"]
    assert r["regione"] == "Lombardia"
    pavia = next(x for x in r["risultati"] if x["codice"] == "26E05265")
    assert pavia["ente"].endswith("DI PAVIA") and pavia["posti"] == 20
    assert pavia["tipo"] == "bando" and pavia["regione"] == "Lombardia"
    assert pavia["numero_gu"] == 76 and pavia["data_gu"] == "2026-10-02"
    assert pavia["link"].endswith("/eli/id/2026/10/02/26E05265/S4")
    assert all(x["regione"] == "Lombardia" for x in r["risultati"])
    assert r["regione_non_determinata"] == 0
    # a second search is free: index and issues are cached
    n = len(seen)
    r2 = await service.cerca_concorsi("infermiere", regione="Lombardia")
    assert len(seen) == n and r2["richieste_effettuate"] == 0 and r2["totale"] == r["totale"]


async def test_cerca_concorsi_filters_types_and_region_unknowns():
    service, *_ = make_service()
    only_calls = await service.cerca_concorsi("diario")
    assert only_calls["totale"] == 0  # diari are not calls
    more = await service.cerca_concorsi("diario", includi_altri_atti=True)
    assert more["totale"] > 0 and {x["tipo"] for x in more["risultati"]} == {"diario_prove"}
    # region filter: unknown-region items are counted, not silently dropped
    lazio = await service.cerca_concorsi("assistente amministrativo", regione="Lazio")
    assert lazio["totale"] > 0 and all(x["regione"] == "Lazio" for x in lazio["risultati"])
    cam = await service.cerca_concorsi("ragioniere", regione="Lazio", includi_altri_atti=True)
    assert cam["regione_non_determinata"] >= 1 and cam["totale"] == 0
    assert any("non determinata" in n for n in cam["note"])
    no_filter = await service.cerca_concorsi("ragioniere", includi_altri_atti=True)
    assert no_filter["totale"] >= 1 and no_filter["regione_non_determinata"] is None
    assert no_filter["risultati"][0]["regione"] is None
    # keyword plural/singular and result limit
    plural = await service.cerca_concorsi("infermieri", limite=1)
    assert plural["mostrati"] == 1 and plural["totale"] >= 1


async def test_cerca_concorsi_errors_and_aperti_window():
    service, seen, _cache, _ = make_service()
    with pytest.raises(ServiceError, match="parola chiave"):
        await service.cerca_concorsi("  ")
    with pytest.raises(ServiceError, match="parola chiave"):
        await service.cerca_concorsi("!!!")
    with pytest.raises(ValueError, match="non riconosciuta"):
        await service.cerca_concorsi("infermiere", regione="Groenlandia")
    assert seen == []  # bad input never reaches the network


async def test_cerca_concorsi_window_excludes_old_cached_issues_unless_asked():
    from datetime import timedelta

    from gazzetta_mcp.models import Serie, Sommario, SommarioVoce

    service, _seen, cache, _ = make_service()
    old_day = date(2026, 10, 5) - timedelta(days=60)
    voce = SommarioVoce(
        "26E00001",
        "Concorso pubblico per un posto di bibliotecario",
        "COMUNE DI SIENA",
        "ENTI LOCALI",
        "https://x/26E00001",
    )
    cache.put_sommario(Sommario(Serie.S4, old_day, 40, "https://x/h", "https://x/p", [voce]))
    base = await service.cerca_concorsi("bibliotecario")
    assert base["totale"] == 0
    wide = await service.cerca_concorsi("bibliotecario", aperti=False)
    assert wide["totale"] == 1 and wide["risultati"][0]["regione"] == "Toscana"
    assert wide["risultati"][0]["data_gu"] == old_day.isoformat()


async def test_ensure_recent_sommari_respects_defaults_and_hard_cap():
    from gazzetta_mcp.models import Serie

    service, seen, cache, _ = make_service()
    sg = await service.ensure_recent_sommari(Serie.SG)  # default 7
    assert len(sg.sommari) == 7 and sg.richieste == 8 and len(seen) == 8
    assert cache.stats()["sommari"] == 7
    again = await service.ensure_recent_sommari(Serie.SG)
    assert again.richieste == 0 and len(seen) == 8
    # asking for more costs only the missing ones, and never beyond the hard cap of 12
    more = await service.ensure_recent_sommari(Serie.SG, max_issues=500)
    assert len(more.sommari) == 12 and more.richieste == 5 and len(seen) == 13
    # newest first, numbers taken from the index (nothing guessed)
    assert [s.numero for s in more.sommari] == list(range(230, 218, -1))
    one = await service.ensure_recent_sommari(Serie.SG, max_issues=1)
    assert [s.numero for s in one.sommari] == [230]


async def test_ensure_recent_sommari_survives_a_broken_issue():
    from gazzetta_mcp.models import Serie

    service, _seen, _cache, _ = make_service(fail={"/2026/09/22/73/": 500})
    r = await service.ensure_recent_sommari(Serie.S4)
    assert len(r.sommari) == 7
    assert any("73" in n and "non caricato" in n for n in r.notes)
    out = await service.cerca_concorsi("infermiere")
    assert out["totale"] >= 1 and any("non caricato" in n for n in out["note"])


async def test_ensure_recent_sommari_stops_after_repeated_failures():
    from gazzetta_mcp.models import Serie

    service, seen, *_ = make_service(fail={"/S4/html": 503})
    r = await service.ensure_recent_sommari(Serie.S4)
    assert r.sommari == [] and r.richieste == 1
    assert len(seen) == 1 + 3  # the index plus three failed attempts, then it gives up


async def test_index_failure_falls_back_to_the_cache():
    service, _seen, cache, _ = make_service()
    await service.cerca_concorsi("infermiere")  # fills the cache
    cache._conn.execute("DELETE FROM http_pages")  # the index must be fetched again
    service2, seen2, _, _ = make_service(cache=cache, fail={"/30giorni/": 500})
    r = await service2.cerca_concorsi("infermiere")
    assert r["totale"] >= 1 and len(seen2) == 1
    assert any("elenco dei numeri" in n for n in r["note"])


async def test_codes_seen_are_remembered_so_leggi_atto_needs_no_date():
    from gazzetta_mcp.models import Serie

    service, _seen, cache, _ = make_service()
    await service.ensure_recent_sommari(Serie.S4, max_issues=1)
    assert cache.find_codice("26E05478") == (Serie.S4, date(2026, 10, 2))
    # leggi_atto(codice) now needs neither date nor series
    assert service._locate("26E05478", None, None) == (Serie.S4, date(2026, 10, 2), False)


async def test_cerca_cold_start_loads_sg_and_s4_and_states_the_range():
    service, seen, _cache, _ = make_service()
    r = await service.cerca("infermiere")
    check(r)
    assert r["totale"] > 0
    loaded = {x["serie"]: x for x in r["numeri_caricati"]}
    assert loaded["SG"]["numeri"] == 7 and loaded["S4"]["numeri"] == 8
    assert loaded["S4"]["dal"] == "2026-09-08" and loaded["S4"]["al"] == "2026-10-02"
    assert "NON viene cercato il testo completo" in r["copertura"]
    assert "S4 dal 2026-09-08 al 2026-10-02" in r["copertura"]
    assert len(seen) == 2 + 7 + 8
    n = len(seen)
    await service.cerca("infermiere")
    assert len(seen) == n  # second call costs nothing


async def test_cerca_single_series_and_no_refresh_modes():
    service, seen, *_ = make_service()
    r = await service.cerca("decreto", serie="SG")
    assert [x["serie"] for x in r["numeri_caricati"]] == ["SG"]
    assert all(q.url.path != "/30giorni/concorsi" for q in seen)
    offline, seen2, *_ = make_service()
    r2 = await offline.cerca("decreto", aggiorna=False)
    assert seen2 == [] and r2["totale"] == 0 and "vuota" in r2["messaggio"]
    other, seen3, *_ = make_service()
    r3 = await other.cerca("sentenza", serie="S1")  # no index known for S1: cache only
    assert seen3 == [] and r3["totale"] == 0


async def test_cerca_without_refresh_behaves_as_before():
    service, seen, *_ = make_service()
    await service.sommario("2026-10-03", "SG")
    n = len(seen)
    r = await service.cerca("decreto", serie="SG", aggiorna=False)
    check(r)
    assert len(seen) == n and r["numeri_caricati"] == []
    assert "solo i contenuti gia' presenti nella cache locale" in r["copertura"]


async def test_rimando_normattiva():
    service, *_ = make_service()
    r = service.rimando_normattiva("legge 5 agosto 2026, n. 140")
    check(r)
    assert r["link_normattiva"].startswith("https://www.normattiva.it/uri-res/N2Ls?urn:nir")
    with pytest.raises(ValueError, match="Non riesco"):
        service.rimando_normattiva("boh")


async def test_cerca_empty_cache_then_results():
    service, *_ = make_service()
    empty = await service.cerca("decreto", aggiorna=False)
    check(empty)
    assert empty["totale"] == 0 and "vuota" in empty["messaggio"]
    atto = await service.leggi_atto("26A05182", data="2026-10-03")
    word = atto["titolo"].split()[-1]
    r = await service.cerca(
        word, serie="SG", dal="2026-10-01", al="2026-10-05", limite=5, aggiorna=False
    )
    check(r)
    assert any(h["codice"] == "26A05182" for h in r["risultati"])
    with pytest.raises(ServiceError, match="AAAA-MM-GG"):
        await service.cerca("x", dal="ieri")


def test_user_message_never_leaks():
    assert "Riprova" in user_message(GuHttpError("boom http://x"))
    msg = user_message(RuntimeError("secret"))
    assert msg.startswith("Errore interno imprevisto") and "secret" not in msg


async def test_aclose_closes_resources():
    service, _, _, client = make_service()
    await service.aclose()
    assert client._http.is_closed
