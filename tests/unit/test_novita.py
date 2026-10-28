"""novita_argomento: the memory of the last check, with a scripted search (no network)."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from gazzetta_mcp.cache.sqlite import Controllo, SqliteCache
from gazzetta_mcp.models import DISCLAIMER, Serie
from gazzetta_mcp.novita import chiave_argomento, novita_argomento
from gazzetta_mcp.service import Limits, ServiceError
from gazzetta_mcp.tools.novita import register_novita

from ._service_helpers import TODAY, make_service

BASE = "https://www.gazzettaufficiale.it"


def hit(codice: str, giorno: str, titolo: str = "Appalti pubblici") -> dict:
    return {
        "codice": codice,
        "serie": "SG",
        "data": giorno,
        "titolo": titolo,
        "estratto": titolo,
        "link": f"{BASE}/atto/{codice}",
        "punteggio": 1.0,
        "origine": "cache",
    }


def caricati(dal: str, al: str, serie: str = "SG") -> dict:
    return {"serie": serie, "dal": dal, "al": al, "numeri": 3, "richieste_effettuate": 0}


class FakeService:
    """Stands in for GazzettaService: ``cerca`` returns what the test scripts."""

    def __init__(self) -> None:
        self._cache = SqliteCache(":memory:")
        self.now = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
        self._base = BASE
        self.hits: list[dict] = []
        self.numeri: list[dict] = []
        self.note: list[str] = []
        self.calls: list[tuple] = []

    def _today(self) -> date:
        return TODAY

    def _now(self) -> datetime:
        return self.now

    def _result(self, data, fonte):
        return {**data, "fonte": list(dict.fromkeys(fonte)), "avvertenza": DISCLAIMER}

    async def cerca(self, *args):
        self.calls.append(args)
        dal = args[3]
        return {
            "numeri_caricati": self.numeri,
            "note": list(self.note),
            "risultati": [h for h in self.hits if h["data"] >= dal],
        }


@pytest.fixture
def svc() -> FakeService:
    s = FakeService()
    s.numeri = [caricati("2026-09-10", "2026-10-03"), caricati("2026-09-10", "2026-10-02", "S4")]
    return s


async def chiedi(svc, argomento="appalti", **kw):
    return await novita_argomento(svc, argomento, **kw)


def stato(svc, argomento="appalti", serie=None):
    return svc._cache.get_controllo(chiave_argomento(argomento, serie))


def memorizza(svc, fino: date, codici=frozenset()):
    svc._cache.put_controllo(
        Controllo(chiave_argomento("appalti", None), "appalti", "", fino, codici, svc.now)
    )


# -- key ---------------------------------------------------------------------------------------


def test_same_topic_written_differently_has_one_key():
    chiavi = {
        chiave_argomento(t, None)
        for t in ("Appalti", "appalti", "APPALTI!", " appalto ", "gli appalti")
    }
    assert len(chiavi) == 1
    assert chiave_argomento("bonus edilizia", None) == chiave_argomento("Edilizia, bonus", None)


def test_different_topics_and_series_have_different_keys():
    assert chiave_argomento("appalti", None) != chiave_argomento("concorsi", None)
    assert chiave_argomento("appalti", None) != chiave_argomento("appalti", Serie.SG)


def test_topic_without_words_is_refused():
    with pytest.raises(ServiceError):
        chiave_argomento("!!", None)


# -- first check, then only what is new -----------------------------------------------------------


async def test_first_check_shows_last_week_and_says_so(svc):
    svc.hits = [
        hit("26A00001", "2026-09-20"),  # older than a week: not shown
        hit("26A00002", "2026-09-30"),
        hit("26A00003", "2026-10-03"),  # newer than the covered day: waits
    ]
    r = await chiedi(svc)
    assert r["primo_controllo"] is True
    assert r["periodo_cercato"] == {"dal": "2026-09-28", "al": "2026-10-02"}
    assert "prima volta" in r["copertura"] and "7 giorni" in r["copertura"]
    assert "titoli" in r["copertura"] and "parziale" in r["copertura"]
    assert [h["codice"] for h in r["risultati"]] == ["26A00002"]
    assert r["avvertenza"] == DISCLAIMER and r["fonte"]
    assert svc.calls[0][3] == "2026-09-28"


async def test_second_check_returns_only_newer_acts(svc):
    svc.hits = [hit("26A00002", "2026-09-30"), hit("26A00003", "2026-10-02")]
    first = await chiedi(svc)
    assert first["segnato_come_letto"] is True
    assert stato(svc).coperto_fino == date(2026, 10, 2)

    svc.hits.append(hit("26A00004", "2026-10-03"))
    svc.numeri = [caricati("2026-09-10", "2026-10-03"), caricati("2026-09-10", "2026-10-03", "S4")]
    second = await chiedi(svc)
    assert second["primo_controllo"] is False
    assert [h["codice"] for h in second["risultati"]] == ["26A00004"]
    assert second["periodo_cercato"]["dal"] == "2026-10-02"
    assert svc.calls[1][3] == "2026-10-02"


async def test_same_day_act_published_after_the_check_is_not_lost(svc):
    svc.hits = [hit("26A00002", "2026-10-02")]
    await chiedi(svc)
    svc.hits.append(hit("26A00009", "2026-10-02"))  # same day, appeared later
    r = await chiedi(svc)
    assert [h["codice"] for h in r["risultati"]] == ["26A00009"]


async def test_same_topic_written_differently_shares_the_memory(svc):
    svc.hits = [hit("26A00002", "2026-10-02")]
    await chiedi(svc, "Appalti")
    r = await chiedi(svc, "appalto")
    assert r["primo_controllo"] is False
    assert r["risultati"] == []


async def test_two_topics_do_not_mix(svc):
    svc.hits = [hit("26A00002", "2026-10-02")]
    await chiedi(svc, "appalti")
    r = await chiedi(svc, "concorsi")
    assert r["primo_controllo"] is True
    assert [h["codice"] for h in r["risultati"]] == ["26A00002"]


async def test_same_topic_on_two_series_is_remembered_separately(svc):
    svc.hits = [hit("26A00002", "2026-10-02")]
    await chiedi(svc, "appalti", serie="SG")
    svc.numeri = [caricati("2026-09-10", "2026-10-02", "S4")]
    r = await chiedi(svc, "appalti", serie="S4")
    assert r["primo_controllo"] is True


# -- what must not be marked as read ----------------------------------------------------------------


async def test_without_segna_come_letto_nothing_changes(svc):
    svc.hits = [hit("26A00002", "2026-10-02")]
    r = await chiedi(svc, segna_come_letto=False)
    assert r["segnato_come_letto"] is False
    assert stato(svc) is None
    again = await chiedi(svc, segna_come_letto=False)
    assert [h["codice"] for h in again["risultati"]] == ["26A00002"]


async def test_empty_answer_advances_only_to_real_coverage(svc):
    svc.now = datetime(2026, 10, 5, 23, 0, tzinfo=timezone.utc)
    r = await chiedi(svc)
    assert r["risultati"] == [] and "Nessuna novita'" in r["messaggio"]
    # not the clock (2026-10-05): the last issue really loaded by both series
    assert stato(svc).coperto_fino == date(2026, 10, 2)
    assert stato(svc).controllato_il == svc.now


async def test_series_loaded_partially_does_not_advance(svc):
    svc.numeri = [caricati("2026-09-10", "2026-10-03")]  # S4 missing: not looked at
    svc.hits = [hit("26A00002", "2026-10-02")]
    r = await chiedi(svc)
    assert [h["codice"] for h in r["risultati"]] == ["26A00002"]
    assert r["segnato_come_letto"] is False
    assert stato(svc) is None
    assert any("giorno" in n for n in r["note"])


async def test_coverage_is_the_shortest_of_the_series(svc):
    svc.numeri = [caricati("2026-09-10", "2026-10-03"), caricati("2026-09-10", "2026-09-29", "S4")]
    r = await chiedi(svc)
    assert r["periodo_cercato"]["al"] == "2026-09-29"
    assert stato(svc).coperto_fino == date(2026, 9, 29)


async def test_nothing_loaded_does_not_advance(svc):
    svc.numeri = []  # cerca answered "cache vuota" without loading anything
    r = await chiedi(svc)
    assert r["segnato_come_letto"] is False and stato(svc) is None
    assert r["periodo_cercato"]["al"] is None


async def test_series_without_automatic_update_does_not_advance(svc):
    r = await chiedi(svc, serie="S1")
    assert r["segnato_come_letto"] is False and stato(svc) is None


async def test_limit_exceeded_acts_beyond_are_not_marked_read(svc):
    svc.hits = [
        hit("26A00005", "2026-09-30"),
        hit("26A00001", "2026-10-01"),
        hit("26A00002", "2026-10-02"),
        hit("26A00010", "2026-10-02", "Altro appalto"),
    ]
    r = await chiedi(svc, limite=2)
    assert r["totale_novita"] == 4 and r["mostrate"] == 2 and r["non_mostrate"] == 2
    assert [h["codice"] for h in r["risultati"]] == ["26A00005", "26A00001"]  # oldest first
    assert "richiama" in r["messaggio"]
    # the check stops at the last act shown, not at the covered day
    assert stato(svc).coperto_fino == date(2026, 10, 1)
    r2 = await chiedi(svc, limite=2)
    assert [h["codice"] for h in r2["risultati"]] == ["26A00002", "26A00010"]
    assert r2["non_mostrate"] == 0
    assert stato(svc).coperto_fino == date(2026, 10, 2)  # now the covered day


async def test_limit_inside_one_day_keeps_the_rest_for_next_time(svc):
    svc.hits = [hit("26A00001", "2026-10-02"), hit("26A00002", "2026-10-02")]
    r = await chiedi(svc, limite=1)
    assert [h["codice"] for h in r["risultati"]] == ["26A00001"]
    r2 = await chiedi(svc, limite=1)
    assert [h["codice"] for h in r2["risultati"]] == ["26A00002"]


async def test_search_cap_reached_does_not_mark_anything(svc):
    svc.hits = [hit(f"26A{i:05d}", "2026-10-02") for i in range(100)]
    r = await chiedi(svc)
    assert r["segnato_come_letto"] is False and stato(svc) is None
    assert any("troppi risultati" in n for n in r["note"])


async def test_acts_newer_than_coverage_wait_for_the_next_check(svc):
    svc.hits = [hit("26A00002", "2026-10-02"), hit("26A00003", "2026-10-04")]
    r = await chiedi(svc)
    assert [h["codice"] for h in r["risultati"]] == ["26A00002"]
    assert any("piu' recenti" in n for n in r["note"])
    svc.numeri = [caricati("2026-09-10", "2026-10-05"), caricati("2026-09-10", "2026-10-05", "S4")]
    r2 = await chiedi(svc)
    assert [h["codice"] for h in r2["risultati"]] == ["26A00003"]


# -- clock and gaps ------------------------------------------------------------------------------


async def test_clock_before_last_check_changes_nothing(svc):
    memorizza(svc, date(2026, 10, 20))
    svc.hits = [hit("26A00002", "2026-10-02")]
    r = await chiedi(svc)
    assert r["risultati"] == [] and r["segnato_come_letto"] is False
    assert stato(svc).coperto_fino == date(2026, 10, 20)
    assert any("orologio" in n for n in r["note"])


async def test_never_moves_back(svc):
    memorizza(svc, date(2026, 10, 3))
    svc.numeri = [caricati("2026-09-10", "2026-09-25"), caricati("2026-09-10", "2026-09-25", "S4")]
    r = await chiedi(svc)
    assert r["segnato_come_letto"] is False
    assert stato(svc).coperto_fino == date(2026, 10, 3)


async def test_gap_between_last_check_and_loaded_issues_is_declared(svc):
    memorizza(svc, date(2026, 8, 1))
    r = await chiedi(svc)
    assert any("potrebbero mancare" in n for n in r["note"])


async def test_search_notes_are_passed_on(svc):
    svc.note = ["Aggiornamento della serie S4 non riuscito: boom"]
    r = await chiedi(svc)
    assert "Aggiornamento della serie S4 non riuscito: boom" in r["note"]


async def test_storage_failure_is_a_note_not_an_error(svc, monkeypatch):
    def boom(_):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(svc._cache, "put_controllo", boom)
    r = await chiedi(svc)
    assert r["segnato_come_letto"] is False
    assert any("niente segnato" in n for n in r["note"])


async def test_memory_is_written_after_the_answer_is_built(svc, monkeypatch):
    svc.hits = [hit("26A00002", "2026-10-02")]

    def broken(*_):
        raise RuntimeError("x")

    monkeypatch.setattr(svc, "_result", broken)
    with pytest.raises(RuntimeError):
        await chiedi(svc)
    assert stato(svc) is None  # building the answer failed: the check did not move


async def test_empty_topic_is_refused(svc):
    with pytest.raises(ServiceError, match="argomento"):
        await chiedi(svc, "   ")


# -- through the real service and the MCP tool, offline ---------------------------------------------


@pytest.fixture
async def client():
    service, *_ = make_service(limits=Limits(recent_issues_sg=2, recent_issues_s4=2))
    mcp = FastMCP("test")
    register_novita(mcp, lambda: service)
    async with Client(mcp) as c:
        yield c


async def test_tool_end_to_end_with_real_search(client):
    r1 = (await client.call_tool("novita_argomento", {"argomento": "decreto"})).data
    assert r1["avvertenza"] == DISCLAIMER
    assert r1["fonte"] and all(u.startswith("http") for u in r1["fonte"])
    assert r1["primo_controllo"] is True and r1["periodo_cercato"]["al"]
    assert r1["segnato_come_letto"] is True
    r2 = (await client.call_tool("novita_argomento", {"argomento": "Decreti"})).data
    assert r2["primo_controllo"] is False
    assert r2["totale_novita"] == 0  # nothing newer than the last covered day


async def test_tool_errors_are_italian(client):
    with pytest.raises(ToolError, match="argomento"):
        await client.call_tool("novita_argomento", {"argomento": " "})
    with pytest.raises(ToolError, match="non esiste"):
        await client.call_tool("novita_argomento", {"argomento": "x", "serie": "ZZ"})
