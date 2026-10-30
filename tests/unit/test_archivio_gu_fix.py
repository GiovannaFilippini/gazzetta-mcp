"""GU ingestion: backward queue, graph, partial texts, poison issues. No network."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from gazzetta_mcp.archivio import ArchiveStore
from gazzetta_mcp.archivio.acquisizione_gu import (
    accoda_indietro,
    acquisisci_numero,
    recupera_indietro,
)
from gazzetta_mcp.models import Serie
from gazzetta_mcp.parsing import GuParser
from gazzetta_mcp.sources.gu import GuHttpError

from .test_archivio_gu import DAY, ISSUE, N_ACTS, FakeClient, stato, stub_issue, voce


@pytest.fixture
def store():
    with ArchiveStore(":memory:") as s:
        yield s


@pytest.fixture
def client():
    return FakeClient()


async def no_sleep(s: float) -> None:
    return None


def offer_sg(client: FakeClient, first: date, numero: int, days: int) -> None:
    """Offer the issues going back from ``first`` (a Monday-Saturday calendar, no holidays)."""
    d, n = first, numero
    for _ in range(days):
        if d.weekday() != 6:
            client.issues[(Serie.SG, d, n)] = stub_issue(d, n)
            n -= 1
        d -= timedelta(days=1)


# --- accoda_indietro --------------------------------------------------------------------


async def test_accoda_indietro_numbers_the_days_before_the_oldest_known(client, store):
    start = date(2026, 9, 7)  # Monday, issue 207 (as in the real list)
    store.aggiungi_numeri([(Serie.SG, start, 207)])
    offer_sg(client, start - timedelta(days=1), 206, 10)
    n = await accoda_indietro(client, GuParser(), store, Serie.SG, quanti=4)
    assert n == 4
    got = {(v.data, v.numero) for v in store.prossimi_numeri(Serie.SG, 10)}
    # Saturday 5/9 = 206, 4/9 = 205, 3/9 = 204, 2/9 = 203: Sunday 6/9 is skipped
    assert (date(2026, 9, 5), 206) in got and (date(2026, 9, 2), 203) in got
    assert not any(v[0] == date(2026, 9, 6) for v in got)
    assert store.get_stato("gu.SG.cursore_indietro") == "2026-09-02"
    assert client.count("sommario") == 4  # one request per day, no more

    # resumes from the cursor
    assert await accoda_indietro(client, GuParser(), store, Serie.SG, quanti=2) == 2
    assert store.get_stato("gu.SG.cursore_indietro") == "2026-08-31"
    assert (date(2026, 8, 31), 201) in {
        (v.data, v.numero) for v in store.prossimi_numeri(Serie.SG, 20)
    }


async def test_accoda_indietro_marks_a_holiday_as_vuoto_and_goes_on(client, store):
    start = date(2026, 6, 4)  # Thursday
    store.aggiungi_numeri([(Serie.SG, start, 120)])
    # Tuesday 2 June (holiday) has no issue: Monday 1 June is 119, Saturday 30 May is 118
    client.issues[(Serie.SG, date(2026, 6, 3), 119)] = stub_issue(date(2026, 6, 3), 119)
    client.issues[(Serie.SG, date(2026, 6, 1), 118)] = stub_issue(date(2026, 6, 1), 118)
    client.issues[(Serie.SG, date(2026, 5, 30), 117)] = stub_issue(date(2026, 5, 30), 117)
    assert await accoda_indietro(client, GuParser(), store, Serie.SG, quanti=3) == 3
    assert stato(store, giorno=date(2026, 6, 2))["stato"] == "vuoto"
    assert stato(store, giorno=date(2026, 6, 2))["numero"] is None
    assert stato(store, giorno=date(2026, 5, 30))["numero"] == 117


async def test_accoda_indietro_gives_up_after_unexpected_gaps(client, store):
    store.aggiungi_numeri([(Serie.SG, date(2026, 9, 7), 207)])  # nothing on offer
    assert await accoda_indietro(client, GuParser(), store, Serie.SG, quanti=50) == 0
    assert client.count("sommario") == 3  # bounded, not an endless search
    assert "in a row" in (store.get_stato("gu.SG.ultimo_stop") or "")
    assert store.conteggio_numeri(Serie.SG) == {"da_fare": 1}  # doubtful days left unmarked


async def test_accoda_indietro_stops_at_the_start_of_the_year_if_the_last_number_is_unknown(
    client, store
):
    store.aggiungi_numeri([(Serie.SG, date(2026, 1, 3), 2)])
    offer_sg(client, date(2026, 1, 2), 1, 1)
    assert await accoda_indietro(client, GuParser(), store, Serie.SG, quanti=10) == 1
    assert "non determinabile" in (store.get_stato("gu.SG.ultimo_stop") or "")


async def test_accoda_indietro_uses_the_weekly_pattern_of_s4(client, store):
    store.aggiungi_numeri([(Serie.S4, date(2026, 10, 2), 76)])  # Friday
    client.issues[(Serie.S4, date(2026, 9, 29), 75)] = stub_issue(date(2026, 9, 29), 75)
    client.issues[(Serie.S4, date(2026, 9, 25), 74)] = stub_issue(date(2026, 9, 25), 74)
    assert await accoda_indietro(client, GuParser(), store, Serie.S4, quanti=2) == 2
    assert client.count("sommario") == 2


async def test_accoda_indietro_other_series_and_empty_store_do_nothing(client, store):
    store.aggiungi_numeri([(Serie.S5, date(2026, 10, 2), 112)])
    assert await accoda_indietro(client, GuParser(), store, Serie.S5, quanti=5) == 0
    assert await accoda_indietro(client, GuParser(), store, Serie.SG, quanti=5) == 0
    assert client.calls == []


async def test_accoda_indietro_raises_network_errors_keeping_progress(client, store):
    start = date(2026, 9, 7)
    store.aggiungi_numeri([(Serie.SG, start, 207)])
    offer_sg(client, start - timedelta(days=1), 206, 10)
    client.fail["sommario"] = [GuHttpError("Unexpected HTTP status 503")]
    with pytest.raises(GuHttpError):
        await accoda_indietro(client, GuParser(), store, Serie.SG, quanti=3)
    assert store.get_stato("gu.SG.cursore_indietro") is None


async def test_recupera_indietro_queues_older_issues_when_the_queue_is_empty(client, store):
    start = date(2026, 9, 7)
    store.aggiungi_numeri([(Serie.SG, start, 207)])
    store.segna_numero(Serie.SG, start, "fatto")
    offer_sg(client, start - timedelta(days=1), 206, 10)
    esito = await recupera_indietro(
        client, GuParser(), store, Serie.SG, max_numeri=2, sleep=no_sleep
    )
    assert (esito.numeri_elaborati, esito.fermato) == (2, False)
    assert store.conteggio_numeri(Serie.SG)["vuoto"] == 2


async def test_recupera_indietro_reports_a_stop_while_queueing(client, store):
    start = date(2026, 9, 7)
    store.aggiungi_numeri([(Serie.SG, start, 207)])
    store.segna_numero(Serie.SG, start, "fatto")
    client.fail["sommario"] = [GuHttpError("Unexpected HTTP status 429")] * 10
    esito = await recupera_indietro(
        client, GuParser(), store, Serie.SG, max_numeri=2, sleep=no_sleep
    )
    assert esito.fermato and "429" in (esito.motivo or "")


# --- graph ------------------------------------------------------------------------------


async def test_gu_acts_feed_the_graph(client, store):
    store.aggiungi_numeri([(Serie.SG, DAY, ISSUE)])
    await acquisisci_numero(client, GuParser(), store, voce())
    n_archi = store.read("SELECT COUNT(*) AS n FROM archi")[0]["n"]
    n_urn = store.read("SELECT COUNT(*) AS n FROM atti WHERE urn IS NOT NULL")[0]["n"]
    assert n_archi > 0 or n_urn > 0
    assert all(a.fonte == "gu" for a in store.archi_di("26A05182"))


# --- partial texts ----------------------------------------------------------------------


async def test_partial_act_is_replaced_by_the_gu_text_and_full_one_is_not_touched(client, store):
    with ArchiveStore(":memory:") as other:  # a reference copy of the full act
        other.aggiungi_numeri([(Serie.SG, DAY, ISSUE)])
        await acquisisci_numero(client, GuParser(), other, voce())
        full = other.get_atto("26A05182")
    assert full is not None
    client.calls.clear()

    # as if it came from Normattiva: first article only
    store.put_atto(replace(full, testo="Art. 1 only"), fonte="normattiva", completo=False)
    store.aggiungi_numeri([(Serie.SG, DAY, ISSUE)])
    assert not store.ha_testo_completo("26A05182")
    client.calls.clear()
    nuovi = await acquisisci_numero(client, GuParser(), store, voce())
    assert nuovi == N_ACTS - 1  # the partial one is replaced, not counted as new
    assert store.ha_testo_completo("26A05182")
    assert store.get_atto("26A05182").testo == full.testo
    assert client.count("scheda") == N_ACTS  # the partial one plus the 16 missing

    client.calls.clear()
    await acquisisci_numero(client, GuParser(), store, voce())
    assert client.count("scheda") == 0  # full texts are never downloaded again


async def test_series_without_text_url_stay_partial_and_are_not_rewritten(client, store):
    html = __import__("pathlib").Path(__file__).parent.parent / "fixtures" / "real"
    client.issues[(Serie.S5, DAY, ISSUE)] = (html / "sommario_sg_2026-10-03_230.html").read_bytes()
    store.aggiungi_numeri([(Serie.S5, DAY, ISSUE)])
    v = voce(serie=Serie.S5)
    assert await acquisisci_numero(client, GuParser(), store, v) == N_ACTS
    assert not store.ha_testo_completo("26A05182")
    assert store.read("SELECT testo_completo FROM atti LIMIT 1")[0]["testo_completo"] == 0
    assert await acquisisci_numero(client, GuParser(), store, v) == 0


# --- poison pill ------------------------------------------------------------------------


async def test_persistent_network_error_burns_attempts_until_the_issue_is_dropped(client, store):
    store.aggiungi_numeri([(Serie.SG, DAY, ISSUE), (Serie.SG, date(2026, 10, 2), 229)])
    client.issues[(Serie.SG, date(2026, 10, 2), 229)] = stub_issue(date(2026, 10, 2), 229)
    for _ in range(5):
        client.fail["sommario"] = [GuHttpError("Unexpected HTTP status 500")] * 10
        esito = await recupera_indietro(
            client, GuParser(), store, Serie.SG, max_numeri=5, sleep=no_sleep
        )
        assert esito.fermato
    row = stato(store)
    assert (row["stato"], row["tentativi"]) == ("errore", 5)  # one attempt per run
    client.fail.clear()
    esito = await recupera_indietro(
        client, GuParser(), store, Serie.SG, max_numeri=5, sleep=no_sleep
    )
    assert not esito.fermato  # the poison issue no longer blocks the next one
    assert stato(store, giorno=date(2026, 10, 2))["stato"] == "vuoto"
