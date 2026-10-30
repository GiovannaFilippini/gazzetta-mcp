"""GU backward queue across the new year: last number of the year before. No network."""

from __future__ import annotations

from datetime import date

import pytest

from gazzetta_mcp.archivio import ArchiveStore
from gazzetta_mcp.archivio.acquisizione_gu import (
    _stima_numero,
    accoda_indietro,
    ultimo_numero_anno,
)
from gazzetta_mcp.models import Serie
from gazzetta_mcp.parsing import GuParser
from gazzetta_mcp.sources.gu import GuHttpError

from .test_archivio_gu import FakeClient, stub_issue
from .test_archivio_gu_fix import offer_sg

SG_DAYS = frozenset(range(6))
S4_DAYS = frozenset({1, 4})


@pytest.fixture
def store():
    with ArchiveStore(":memory:") as s:
        yield s


@pytest.fixture
def client():
    return FakeClient()


def offer(client: FakeClient, serie: Serie, day: date, numero: int) -> None:
    client.issues[(serie, day, numero)] = stub_issue(day, numero)


def test_estimate_matches_the_real_numbers():
    # Verified on the real site: SG 2026-09-07 is 207, 2025-12-31 is 302, 2024-12-31 is 305;
    # S4 2026-10-02 is 76, 2025-12-30 is 101, 2024-12-31 is 104
    assert _stima_numero(date(2026, 9, 7), SG_DAYS) == 207
    assert _stima_numero(date(2025, 12, 31), SG_DAYS) == 302
    assert _stima_numero(date(2024, 12, 31), SG_DAYS) == 305
    assert _stima_numero(date(2026, 10, 2), S4_DAYS) == 76
    assert _stima_numero(date(2025, 12, 30), S4_DAYS) == 101
    assert _stima_numero(date(2024, 12, 31), S4_DAYS) == 104


async def test_last_number_costs_two_requests_when_the_estimate_is_right(client, store):
    offer(client, Serie.SG, date(2025, 12, 31), 302)
    assert await ultimo_numero_anno(client, store, Serie.SG, 2025) == 302
    assert client.count("sommario") == 2  # the anchor, and "is there a 303 that day?"
    assert store.get_stato("gu.SG.ultimo_numero_2025") == "302"
    # saved: no new request
    assert await ultimo_numero_anno(client, store, Serie.SG, 2025) == 302
    assert client.count("sommario") == 2


async def test_a_second_edition_on_the_same_day_is_found(client, store):
    offer(client, Serie.SG, date(2025, 12, 31), 302)
    offer(client, Serie.SG, date(2025, 12, 31), 303)
    assert await ultimo_numero_anno(client, store, Serie.SG, 2025) == 303


async def test_an_extra_edition_on_a_holiday_is_found(client, store):
    offer(client, Serie.SG, date(2025, 12, 30), 301)
    offer(client, Serie.SG, date(2025, 12, 31), 302)
    assert await ultimo_numero_anno(client, store, Serie.SG, 2025) == 302


async def test_last_number_for_s4_uses_the_last_tuesday_or_friday(client, store):
    offer(client, Serie.S4, date(2025, 12, 30), 101)
    assert await ultimo_numero_anno(client, store, Serie.S4, 2025) == 101


async def test_estimate_off_by_one_is_corrected_by_the_page(client, store):
    offer(client, Serie.SG, date(2025, 12, 31), 303)  # one more than the calendar says
    assert await ultimo_numero_anno(client, store, Serie.SG, 2025) == 303


async def test_no_issue_on_the_last_day_goes_back_and_checks_the_days_after(client, store):
    offer(client, Serie.SG, date(2025, 12, 30), 301)  # nothing on Wed 31 Dec
    assert await ultimo_numero_anno(client, store, Serie.SG, 2025) == 301


async def test_undeterminable_number_is_none_and_bounded(client, store):
    assert await ultimo_numero_anno(client, store, Serie.SG, 2025) is None
    assert client.count("sommario") <= 12
    assert store.get_stato("gu.SG.ultimo_numero_2025") is None


async def test_budget_is_respected(client, store):
    assert await ultimo_numero_anno(client, store, Serie.SG, 2025, max_sonde=2) is None
    assert client.count("sommario") == 2


async def test_other_series_have_no_answer(client, store):
    assert await ultimo_numero_anno(client, store, Serie.S5, 2025) is None
    assert client.calls == []


async def test_network_error_is_raised(client, store):
    client.fail["sommario"] = [GuHttpError("Unexpected HTTP status 503")]
    with pytest.raises(GuHttpError):
        await ultimo_numero_anno(client, store, Serie.SG, 2025)
    assert store.get_stato("gu.SG.ultimo_numero_2025") is None


async def test_accoda_indietro_crosses_the_new_year(client, store):
    store.aggiungi_numeri([(Serie.SG, date(2026, 1, 3), 2)])
    offer_sg(client, date(2026, 1, 2), 1, 1)
    offer_sg(client, date(2025, 12, 31), 302, 6)
    n = await accoda_indietro(client, GuParser(), store, Serie.SG, quanti=4)
    assert n == 4
    got = {(v.data, v.numero) for v in store.prossimi_numeri(Serie.SG, 10)}
    assert (date(2026, 1, 2), 1) in got
    assert (date(2025, 12, 31), 302) in got and (date(2025, 12, 29), 300) in got
    assert store.get_stato("gu.SG.ultimo_numero_2025") == "302"
    assert store.get_stato("gu.SG.cursore_indietro") == "2025-12-29"
    assert store.get_stato("gu.SG.ultimo_stop") is None


async def test_accoda_indietro_resumes_across_the_year_from_the_first_issue(client, store):
    store.aggiungi_numeri([(Serie.SG, date(2026, 1, 2), 1)])  # the oldest known is issue 1
    offer_sg(client, date(2025, 12, 31), 302, 6)
    assert await accoda_indietro(client, GuParser(), store, Serie.SG, quanti=2) == 2
    got = {(v.data, v.numero) for v in store.prossimi_numeri(Serie.SG, 10)}
    assert (date(2025, 12, 30), 301) in got


async def test_accoda_indietro_goes_on_in_the_year_before_with_holidays(client, store):
    store.aggiungi_numeri([(Serie.SG, date(2026, 1, 2), 1)])
    # 31 Dec = 302, 30 Dec = 301, 29 Dec = 300, 27 Dec = 299; 25-26 Dec are holidays
    offer(client, Serie.SG, date(2025, 12, 31), 302)
    offer(client, Serie.SG, date(2025, 12, 30), 301)
    offer(client, Serie.SG, date(2025, 12, 29), 300)
    offer(client, Serie.SG, date(2025, 12, 27), 299)
    offer(client, Serie.SG, date(2025, 12, 24), 298)
    assert await accoda_indietro(client, GuParser(), store, Serie.SG, quanti=5) == 5
    assert (date(2025, 12, 24), 298) in {
        (v.data, v.numero) for v in store.prossimi_numeri(Serie.SG, 10)
    }


async def test_accoda_indietro_stops_with_a_reason_if_the_last_number_is_unknown(client, store):
    store.aggiungi_numeri([(Serie.SG, date(2026, 1, 2), 1)])
    assert await accoda_indietro(client, GuParser(), store, Serie.SG, quanti=5) == 0
    assert "non determinabile" in (store.get_stato("gu.SG.ultimo_stop") or "")
    assert client.count("sommario") <= 12


async def test_accoda_indietro_s4_crosses_the_new_year(client, store):
    store.aggiungi_numeri([(Serie.S4, date(2026, 1, 6), 2)])
    offer(client, Serie.S4, date(2026, 1, 2), 1)
    offer(client, Serie.S4, date(2025, 12, 30), 101)
    offer(client, Serie.S4, date(2025, 12, 23), 100)
    assert await accoda_indietro(client, GuParser(), store, Serie.S4, quanti=3) == 3
    assert store.get_stato("gu.S4.ultimo_numero_2025") == "101"
