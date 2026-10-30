"""Daily parser check, with a fake client over the real fixtures. No network."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from gazzetta_mcp.archivio.controllo_parser import Campione, controlla_parser
from gazzetta_mcp.archivio.store import ArchiveStore
from gazzetta_mcp.models import RawPage, Serie
from gazzetta_mcp.parsing import GuParser
from gazzetta_mcp.sources.gu import GuNotFoundError

FIX = Path(__file__).parent.parent / "fixtures" / "real"
DAY = date(2026, 10, 3)


def page(content: bytes) -> RawPage:
    return RawPage("https://x.test", content, "text/html", datetime.now(timezone.utc))


class FakeClient:
    """Serves the real fixtures; ``broken`` maps a method name to the content/exception to use."""

    def __init__(self, broken: dict[str, object] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.broken = broken or {}

    def _serve(self, method: str, label: str, name: str) -> RawPage:
        self.calls.append((method, label))
        what = self.broken.get(method)
        if isinstance(what, Exception):
            raise what
        if isinstance(what, bytes):
            return page(what)
        return page((FIX / name).read_bytes())

    async def get_sommario(self, data, serie, numero):
        name = "sommario_sg_2026-10-03_230.html"
        if serie is Serie.S4:
            name = "sommario_s4_2026-10-02_76.html"
        return self._serve("get_sommario", serie.value, name)

    async def get_atto_scheda(self, codice, data, serie):
        return self._serve("get_atto_scheda", serie.value, "atto_scheda_26A05182_sg.html")

    async def get_atto_testo(self, codice, data, serie, tipo):
        return self._serve("get_atto_testo", serie.value, "atto_testo_26A05182_sg.html")


@pytest.fixture
def store():
    with ArchiveStore(":memory:") as s:
        yield s


SG = Campione(Serie.SG, DAY, 230)


async def test_healthy_parser_is_ok_and_state_is_saved(store):
    client = FakeClient()
    r = await controlla_parser(client, GuParser(), store, campioni=[SG])
    assert r.ok
    assert r.esiti[0].voci == 17 and r.esiti[0].codice_atto == "26A05182"
    assert "OK" in r.testo and "26A05182" in r.testo
    saved = json.loads(store.get_stato("controllo_parser"))
    assert saved["ok"] is True and saved["esiti"][0]["ok"] is True
    # one summary + card + text
    assert [c[0] for c in client.calls] == ["get_sommario", "get_atto_scheda", "get_atto_testo"]


async def test_one_act_per_series_only(store):
    client = FakeClient()
    two_sg = [SG, Campione(Serie.SG, date(2026, 10, 2), 229)]
    await controlla_parser(client, GuParser(), store, campioni=two_sg)
    assert [c[0] for c in client.calls].count("get_atto_scheda") == 1
    assert [c[0] for c in client.calls].count("get_sommario") == 2


async def test_series_without_act_pages_get_only_the_summary(store):
    client = FakeClient()
    r = await controlla_parser(client, GuParser(), store, campioni=[Campione(Serie.S5, DAY, 112)])
    # the fake serves a summary whatever the series; the act is not requested for S5
    assert [c[0] for c in client.calls] == ["get_sommario"]
    assert r.esiti[0].codice_atto is None


async def test_empty_issue_is_reported(store):
    client = FakeClient({"get_sommario": b"<html><body>Nessun risultato</body></html>"})
    r = await controlla_parser(client, GuParser(), store, campioni=[SG])
    assert not r.ok
    assert r.numeri_vuoti == ["SG 2026-10-03 n. 230"]
    assert "numero vuoto" in r.testo and "FALLITO" in r.testo
    assert [c[0] for c in client.calls] == ["get_sommario"]  # no act request after an empty issue
    assert json.loads(store.get_stato("controllo_parser"))["ok"] is False


async def test_changed_act_page_is_a_parser_failure(store):
    client = FakeClient({"get_atto_scheda": b"<html>cambiato</html>", "get_atto_testo": b""})
    r = await controlla_parser(client, GuParser(), store, campioni=[SG])
    assert not r.ok
    problemi = " ".join(r.esiti[0].problemi)
    assert "titolo vuoto" in problemi and "emettitore vuoto" in problemi
    assert "testo vuoto" in problemi


async def test_network_error_does_not_stop_other_samples(store):
    class Flaky(FakeClient):
        async def get_sommario(self, data, serie, numero):
            if serie is Serie.S4:
                raise GuNotFoundError("404")
            return await super().get_sommario(data, serie, numero)

    r = await controlla_parser(
        Flaky(), GuParser(), store, campioni=[Campione(Serie.S4, DAY, 76), SG]
    )
    assert not r.ok
    assert not r.esiti[0].ok and "GuNotFoundError" in r.esiti[0].problemi[0]
    assert r.esiti[1].ok


async def test_parser_exception_is_reported_not_raised(store):
    class Boom(GuParser):
        def parse_sommario(self, *a, **k):
            raise RuntimeError("layout cambiato")

    r = await controlla_parser(FakeClient(), Boom(), store, campioni=[SG])
    assert not r.ok and "layout cambiato" in r.testo


async def test_no_samples_is_not_ok(store):
    r = await controlla_parser(FakeClient(), GuParser(), store, campioni=[])
    assert not r.ok and "nessun campione" in r.testo
    assert json.loads(store.get_stato("controllo_parser"))["ok"] is False


async def test_report_includes_queue_counts(store):
    store.aggiungi_numeri([(Serie.SG, date(2026, 9, 1), 200)])
    r = await controlla_parser(FakeClient(), GuParser(), store, campioni=[SG])
    assert r.numeri_archivio == {"da_fare": 1}
