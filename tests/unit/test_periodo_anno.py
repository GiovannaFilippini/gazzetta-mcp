from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from gazzetta_mcp.models import RawPage, Serie
from gazzetta_mcp.service import Limits, ServiceError
from gazzetta_mcp.sources.gu import GuHttpError

from ._service_helpers import FIX, make_service

SAMPLE = (FIX / "sommario_sg_2026-10-03_230.html").read_bytes().decode("utf-8", "replace")


def issue_page(day: date, numero: int) -> bytes:
    """The sample issue page, relabelled with another date and number."""
    page = SAMPLE.replace("2026/10/03/230", f"{day:%Y/%m/%d}/{numero}")
    page = page.replace("dataPubblicazioneGazzetta=2026-10-03", f"dataPubblicazioneGazzetta={day}")
    return page.replace("numeroGazzetta=230", f"numeroGazzetta={numero}").encode()


class FakeGu:
    """Issues exist only on the given {date: numero}; any other number gives a stub page."""

    def __init__(self, issues: dict[date, int], fail: bool = False) -> None:
        self.issues = issues
        self.fail = fail
        self.asked: list[tuple[date, int]] = []

    async def get_sommario(self, day: date, serie: Serie, numero: int) -> RawPage:
        self.asked.append((day, numero))
        if self.fail:
            raise GuHttpError("down")
        ok = self.issues.get(day) == numero
        return RawPage(
            url=f"x/{day}/{numero}",
            content=issue_page(day, numero) if ok else b"<html><body>stub</body></html>",
            content_type="text/html",
            fetched_at=datetime.now(timezone.utc),
        )


def seeded(issues: dict[date, int], **limits):
    service, _seen, cache, _ = make_service(Limits(**limits))
    newest = max(issues)
    cache.put_sommario(
        service._parser.parse_sommario(
            issue_page(newest, issues[newest]), Serie.SG, newest, issues[newest], service._base
        )
    )
    return service, cache


ISSUES = {
    date(2026, 10, 3): 230,
    date(2026, 10, 2): 229,
    date(2026, 10, 1): 228,
    date(2026, 9, 28): 227,  # nothing on the 29th and 30th: the date is searched
    date(2026, 9, 26): 226,
}


async def test_extend_year_walks_back_with_sequential_numbers():
    service, cache = seeded(ISSUES, older_block=3)
    service._client = FakeGu(ISSUES)
    text = await service._extend_year(Serie.SG)
    for day, numero in list(ISSUES.items())[1:4]:
        assert cache.get_sommario(day, Serie.SG).numero == numero
    assert cache.get_sommario(date(2026, 9, 26), Serie.SG) is None  # block of 3 reached
    assert "fino al 2026-09-28" in text and "aggiunti 3 numeri" in text
    assert "periodo='anno'" in text
    asked = service._client.asked
    assert (date(2026, 9, 30), 227) in asked and (date(2026, 9, 28), 227) in asked
    # the next call continues where the last stopped and costs nothing for cached issues
    service._client.asked.clear()
    text2 = await service._extend_year(Serie.SG)
    assert cache.get_sommario(date(2026, 9, 26), Serie.SG).numero == 226
    assert service._client.asked[0] == (date(2026, 9, 27), 226)
    assert "aggiunti" in text2


async def test_extend_year_fills_gap_before_an_old_cached_issue():
    issues = {**ISSUES, date(2026, 3, 2): 50}
    service, cache = seeded(issues, older_block=10)
    old = date(2026, 3, 2)
    cache.put_sommario(
        service._parser.parse_sommario(issue_page(old, 50), Serie.SG, old, 50, service._base)
    )
    service._client = FakeGu(issues)
    await service._extend_year(Serie.SG)
    # the recent numbers are loaded first, not skipped in favour of the old issue
    assert cache.get_sommario(date(2026, 10, 2), Serie.SG).numero == 229
    assert (date(2026, 10, 2), 229) in service._client.asked


async def test_extend_year_stops_on_errors_and_gaps():
    service, _ = seeded(ISSUES, older_block=5)
    service._client = FakeGu(ISSUES, fail=True)
    assert "Interrotto: errore di rete" in await service._extend_year(Serie.SG)
    service, _ = seeded({date(2026, 10, 3): 230})
    service._client = FakeGu({date(2026, 10, 3): 230})
    assert "non trovato nei 4 giorni" in await service._extend_year(Serie.SG)
    service, _ = seeded({date(2026, 1, 2): 1})
    service._client = FakeGu({})
    service._today = lambda: date(2026, 1, 20)
    assert "primo numero dell'anno" in await service._extend_year(Serie.SG)


async def test_extend_year_reports_completion():
    issues = {date(2026, 10, 3): 230, date(2026, 10, 2): 229}
    service, _ = seeded(issues, year_days=2)
    service._client = FakeGu(issues)
    assert "completa" in await service._extend_year(Serie.SG)
    assert service._client.asked == []  # already inside the target period: nothing to load


async def test_periodo_validation_and_use_in_cerca():
    service, *_ = make_service()
    with pytest.raises(ServiceError, match="periodo"):
        await service.cerca("decreto", periodo="mese")
    r = await service.cerca("decreto", serie="SG", periodo="anno")
    assert any("Cache locale della SG" in n for n in r["note"])
    plain = await service.cerca("decreto", serie="SG")
    assert not any("Cache locale della SG" in n for n in plain["note"])


async def test_local_hits_that_are_repealed_are_left_out():
    from gazzetta_mcp.models import ArchiveResult

    service, *_ = make_service()
    everything = await service.cerca("decreto", solo_vigenti=False, limite=100)
    victim = everything["risultati"][0]["codice"]

    class Repealed:
        async def cerca(self, testo, filtri):
            return ArchiveResult([], 0, [], frozenset({victim}))

    service._archivio = Repealed()
    codes = [x["codice"] for x in (await service.cerca("decreto", limite=100))["risultati"]]
    assert victim not in codes and len(codes) == len(everything["risultati"]) - 1
    keep = await service.cerca("decreto", solo_vigenti=False, limite=100)
    assert victim in [x["codice"] for x in keep["risultati"]]
