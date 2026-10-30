"""Fill on request (``--riempi``): fake source client over the real fixtures, no network."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from gazzetta_mcp.archivio import remoto, riempimento
from gazzetta_mcp.archivio.remoto import ArchivioSolaLettura, create_server
from gazzetta_mcp.archivio.riempimento import (
    LIMITE,
    MAX_RICHIESTE,
    NON_TROVATO,
    OK,
    RIPROVA,
    Riempitore,
    _ClienteContato,
)
from gazzetta_mcp.archivio.store import ArchiveStore
from gazzetta_mcp.models import DISCLAIMER, RawPage, Serie
from gazzetta_mcp.parsing import GuParser
from gazzetta_mcp.sources.gu import GuError, GuHttpError, GuNotFoundError

FIX = Path(__file__).parent.parent / "fixtures" / "real"
IN_FEED = "26A05182"  # in the SG feed fixture
NON_IN_FEED = "26A09999"
IP = "203.0.113.7"


def page(content: bytes) -> RawPage:
    return RawPage("https://example.test/", content, "text/html", datetime.now(timezone.utc))


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail: dict[str, list[Exception]] = {}
        self.empty_text = False
        self.gate: asyncio.Event | None = None  # when set, scheda waits for it

    def _maybe_fail(self, name: str) -> None:
        errors = self.fail.get(name)
        if errors:
            raise errors.pop(0)

    async def get_feed(self, serie: Serie) -> RawPage:
        self.calls.append(("feed", serie.value))
        await asyncio.sleep(0)
        self._maybe_fail("feed")
        return page((FIX / f"rss_{serie.value}.xml").read_bytes())

    async def get_atto_scheda(self, codice: str, data: date, serie: Serie) -> RawPage:
        self.calls.append(("scheda", codice))
        if self.gate is not None:
            await self.gate.wait()
        await asyncio.sleep(0)
        self._maybe_fail("scheda")
        return page((FIX / "atto_scheda_26A05182_sg.html").read_bytes())

    async def get_atto_testo(
        self, codice: str, data: date, serie: Serie, tipo: str | None
    ) -> RawPage:
        self.calls.append(("testo", codice))
        self._maybe_fail("testo")
        if self.empty_text:
            return page(b"<html></html>")
        return page((FIX / "atto_testo_26A05182_sg.html").read_bytes())

    def url_atto(self, codice: str, data: date, serie: Serie) -> str:
        return "x"

    def n(self) -> int:
        return len(self.calls)


class Orologio:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "archivio.sqlite"
    ArchiveStore(path).close()
    return path


@pytest.fixture
def scrittore(db):
    s = ArchiveStore(db)
    yield s
    s.close()


@pytest.fixture
def client():
    return FakeClient()


@pytest.fixture
def orologio():
    return Orologio()


def crea(client, scrittore, orologio, serie=(Serie.SG,), **kw) -> Riempitore:
    return Riempitore(
        client,
        GuParser(),
        scrittore,
        list(serie),
        clock=orologio,
        oggi=lambda: date(2026, 10, 30),
        **kw,
    )


@pytest.fixture
def rie(client, scrittore, orologio):
    return crea(client, scrittore, orologio)


# -- the happy path ------------------------------------------------------------------------


async def test_fills_missing_act_and_saves_like_the_ingestion(rie, client, scrittore, monkeypatch):
    estratti: list[str] = []
    originale = riempimento.salva_archi_atti
    monkeypatch.setattr(
        riempimento,
        "salva_archi_atti",
        lambda store, atti: estratti.extend(a.codice for a in atti) or originale(store, atti),
    )
    esito = await rie.riempi(IN_FEED, ip=IP)
    assert esito.stato == OK
    assert scrittore.ha_testo_completo(IN_FEED)
    assert scrittore.read("SELECT fonte FROM atti")[0]["fonte"] == "gu"
    assert estratti == [IN_FEED]  # links extracted by the shared function
    assert client.n() <= MAX_RICHIESTE
    assert [c[0] for c in client.calls] == ["feed", "scheda", "testo"]
    await rie.aclose()


async def test_numero_gu_is_never_zero(rie, scrittore):
    await rie.riempi(IN_FEED, ip=IP)
    assert scrittore.get_atto(IN_FEED).numero_gu != 0
    await rie.aclose()


async def test_date_and_series_given_skip_the_feed(rie, client, scrittore):
    esito = await rie.riempi(NON_IN_FEED, ip=IP, serie=Serie.SG, data=date(2026, 10, 3))
    assert esito.stato == OK
    assert [c[0] for c in client.calls] == ["scheda", "testo"]
    await rie.aclose()


async def test_every_request_goes_through_the_one_client(rie, client):
    await rie.riempi(IN_FEED, ip=IP)
    assert client.n() == 3  # the filler has no second client of its own
    await rie.aclose()


# -- what is refused before any request ----------------------------------------------------


@pytest.mark.parametrize(
    "codice", ["", "abc", "26A05", "26A05182; DROP", "26A051820000000", "../x"]
)
async def test_invalid_codes_cost_nothing(rie, client, codice):
    assert (await rie.riempi(codice, ip=IP)).stato == NON_TROVATO
    assert client.n() == 0
    await rie.aclose()


async def test_removed_code_is_never_requested(rie, client, scrittore):
    scrittore.rimuovi_atto(IN_FEED, "su richiesta")
    assert (await rie.riempi(IN_FEED, ip=IP)).stato == NON_TROVATO
    assert client.n() == 0
    assert not scrittore.has_atto(IN_FEED)
    await rie.aclose()


async def test_series_not_allowed_is_not_archived(rie, client, scrittore):
    # Asked for explicitly, and inferred from the code letter (E = S4): no request, no row.
    assert (await rie.riempi("26E05478", ip=IP, serie=Serie.S4)).stato == NON_TROVATO
    assert (await rie.riempi("26E05478", ip=IP)).stato == NON_TROVATO
    assert client.n() == 0
    assert scrittore.count_atti() == 0
    await rie.aclose()


async def test_series_found_in_feed_but_not_allowed_is_not_archived(client, scrittore, orologio):
    # Unknown letter: the feeds of SG and S4 are searched; the act turns out to be in S4,
    # which this service does not serve.
    rie = crea(client, scrittore, orologio, serie=(Serie.SG, Serie.S1))
    assert (await rie.riempi("26E05478", ip=IP, data=None)).stato == NON_TROVATO
    assert scrittore.count_atti() == 0
    await rie.aclose()


async def test_implausible_date_is_refused(rie, client):
    assert (await rie.riempi(IN_FEED, ip=IP, data=date(1900, 1, 1))).stato == NON_TROVATO
    assert (await rie.riempi(IN_FEED, ip=IP, data=date(2030, 1, 1))).stato == NON_TROVATO
    assert client.n() == 0
    await rie.aclose()


# -- not found: bounded, no loops -----------------------------------------------------------


async def test_unknown_date_gives_not_found_with_few_requests(rie, client, scrittore):
    assert (await rie.riempi(NON_IN_FEED, ip=IP)).stato == NON_TROVATO
    assert client.n() <= 2  # the latest feed, nothing else
    assert scrittore.count_atti() == 0
    await rie.aclose()


async def test_guessed_series_looks_at_two_feeds_at_most(rie, client):
    assert (await rie.riempi("26X00001", ip=IP)).stato == NON_TROVATO
    assert [c[0] for c in client.calls].count("feed") <= 2
    assert client.n() <= MAX_RICHIESTE
    await rie.aclose()


async def test_scheda_not_found_is_not_found(rie, client, scrittore):
    client.fail["scheda"] = [GuNotFoundError("404")]
    assert (await rie.riempi(IN_FEED, ip=IP)).stato == NON_TROVATO
    assert scrittore.count_atti() == 0
    await rie.aclose()


async def test_budget_of_requests_is_a_hard_limit(client):
    contato = _ClienteContato(client, MAX_RICHIESTE)
    for _ in range(MAX_RICHIESTE):
        await contato.get_feed(Serie.SG)
    with pytest.raises(GuError):
        await contato.get_feed(Serie.SG)
    assert client.n() == MAX_RICHIESTE
    contato.nuovo_lavoro()
    await contato.get_feed(Serie.SG)


async def test_empty_text_is_not_saved(rie, client, scrittore):
    client.empty_text = True
    assert (await rie.riempi(IN_FEED, ip=IP)).stato == NON_TROVATO
    assert scrittore.count_atti() == 0
    await rie.aclose()


# -- network errors, breaker ----------------------------------------------------------------


async def test_network_error_writes_nothing_and_answers_cleanly(rie, client, scrittore):
    client.fail["testo"] = [GuHttpError("HTTP 503")]
    esito = await rie.riempi(IN_FEED, ip=IP)
    assert esito.stato == RIPROVA
    assert "riprova" in esito.messaggio.lower()
    assert scrittore.count_atti() == 0
    await rie.aclose()


async def test_feed_error_is_not_mistaken_for_not_found(rie, client):
    client.fail["feed"] = [GuHttpError("HTTP 429")]
    assert (await rie.riempi(IN_FEED, ip=IP)).stato == RIPROVA
    await rie.aclose()


async def test_unexpected_error_is_contained(rie, client, scrittore):
    client.fail["scheda"] = [RuntimeError("boom")]
    assert (await rie.riempi(IN_FEED, ip=IP)).stato == RIPROVA
    assert scrittore.count_atti() == 0
    await rie.aclose()


async def test_breaker_opens_after_repeated_failures_and_closes_after_the_wait(
    rie, client, scrittore, orologio
):
    client.fail["scheda"] = [GuHttpError("HTTP 429")] * 3
    for codice in ("26A00001", "26A00002", "26A00003"):
        esito = await rie.riempi(codice, ip=IP, serie=Serie.SG, data=date(2026, 10, 3))
        assert esito.stato == RIPROVA
    visti = client.n()
    esito = await rie.riempi(IN_FEED, ip=IP)  # breaker open: no request at all
    assert esito.stato == RIPROVA
    assert client.n() == visti
    orologio.t += 31  # first pause is 30 s
    assert (await rie.riempi(IN_FEED, ip=IP)).stato == OK
    assert scrittore.has_atto(IN_FEED)
    await rie.aclose()


async def test_a_success_resets_the_failure_count(client, scrittore, orologio):
    rie = crea(client, scrittore, orologio, per_ip_ora=50)
    client.fail["scheda"] = [GuHttpError("x"), GuHttpError("x")]
    for codice in ("26A00001", "26A00002"):
        await rie.riempi(codice, ip=IP, serie=Serie.SG, data=date(2026, 10, 3))
    assert (await rie.riempi(IN_FEED, ip=IP)).stato == OK
    client.fail["scheda"] = [GuHttpError("x"), GuHttpError("x")]
    for codice in ("26A00003", "26A00004"):
        await rie.riempi(codice, ip=IP, serie=Serie.SG, data=date(2026, 10, 3))
    visti = client.n()
    await rie.riempi("26A00005", ip=IP, serie=Serie.SG, data=date(2026, 10, 3))
    assert client.n() > visti  # two + two failures with a success between: not open
    await rie.aclose()


# -- dedup, queue, caps ---------------------------------------------------------------------


async def test_same_code_asked_by_many_is_fetched_once(rie, client, scrittore):
    risultati = await asyncio.gather(*(rie.riempi(IN_FEED, ip=f"10.0.0.{i}") for i in range(10)))
    assert {r.stato for r in risultati} == {OK}
    assert client.calls.count(("scheda", IN_FEED)) == 1
    assert scrittore.count_atti() == 1
    await rie.aclose()


async def test_joiners_do_not_use_the_quota(client, scrittore, orologio):
    rie = crea(client, scrittore, orologio, per_ip_ora=1)
    risultati = await asyncio.gather(*(rie.riempi(IN_FEED, ip=IP) for _ in range(5)))
    assert {r.stato for r in risultati} == {OK}
    await rie.aclose()


async def test_full_queue_answers_try_again_without_requests(client, scrittore, orologio):
    rie = crea(client, scrittore, orologio, max_coda=2)
    client.gate = asyncio.Event()
    giorno = date(2026, 10, 3)
    prime = [
        asyncio.create_task(rie.riempi(c, ip=IP, serie=Serie.SG, data=giorno))
        for c in ("26A00001", "26A00002")
    ]
    await asyncio.sleep(0.05)
    assert client.calls == [("scheda", "26A00001")]  # one job at a time
    terza = await rie.riempi("26A00003", ip=IP, serie=Serie.SG, data=giorno)
    assert terza.stato == RIPROVA
    assert ("scheda", "26A00003") not in client.calls
    client.gate.set()
    await asyncio.gather(*prime)
    # The queue drained: a new request is accepted again.
    assert (await rie.riempi("26A00003", ip=IP, serie=Serie.SG, data=giorno)).stato == OK
    await rie.aclose()


async def test_per_ip_cap_with_clear_message_and_other_ip_unaffected(client, scrittore, orologio):
    rie = crea(client, scrittore, orologio, per_ip_ora=2, globale_ora=100)
    giorno = date(2026, 10, 3)
    for c in ("26A00001", "26A00002"):
        assert (await rie.riempi(c, ip=IP, serie=Serie.SG, data=giorno)).stato == OK
    visti = client.n()
    esito = await rie.riempi("26A00003", ip=IP, serie=Serie.SG, data=giorno)
    assert esito.stato == LIMITE
    assert "limite" in esito.messaggio and "2" in esito.messaggio
    assert client.n() == visti
    assert (
        await rie.riempi("26A00003", ip="198.51.100.1", serie=Serie.SG, data=giorno)
    ).stato == OK
    orologio.t += 3600
    assert (await rie.riempi("26A00004", ip=IP, serie=Serie.SG, data=giorno)).stato == OK
    await rie.aclose()


async def test_global_cap(client, scrittore, orologio):
    rie = crea(client, scrittore, orologio, per_ip_ora=10, globale_ora=2)
    giorno = date(2026, 10, 3)
    for i, c in enumerate(("26A00001", "26A00002")):
        assert (await rie.riempi(c, ip=f"10.0.0.{i}", serie=Serie.SG, data=giorno)).stato == OK
    esito = await rie.riempi("26A00003", ip="10.0.0.9", serie=Serie.SG, data=giorno)
    assert esito.stato == LIMITE
    assert "ora" in esito.messaggio
    await rie.aclose()


async def test_refused_requests_do_not_burn_the_global_cap(client, scrittore, orologio):
    rie = crea(client, scrittore, orologio, per_ip_ora=1, globale_ora=2)
    giorno = date(2026, 10, 3)
    assert (await rie.riempi("26A00001", ip=IP, serie=Serie.SG, data=giorno)).stato == OK
    for c in ("26A00002", "26A00003", "26A00004"):  # same IP, over its cap
        assert (await rie.riempi(c, ip=IP, serie=Serie.SG, data=giorno)).stato == LIMITE
    assert (
        await rie.riempi("26A00002", ip="198.51.100.1", serie=Serie.SG, data=giorno)
    ).stato == OK
    await rie.aclose()


def test_invalid_configuration_is_refused(client, scrittore, orologio):
    with pytest.raises(ValueError):
        crea(client, scrittore, orologio, serie=())
    with pytest.raises(ValueError):
        crea(client, scrittore, orologio, per_ip_ora=0)


# -- the MCP tool ----------------------------------------------------------------------------


@pytest.fixture
def lettura(db):
    s = ArchivioSolaLettura(db)
    yield s
    s.close()


def data_of(result):
    return result.data if hasattr(result, "data") and result.data else result.structured_content


async def test_tool_fills_and_returns_the_act_with_notices(lettura, rie, client):
    async with Client(create_server(lettura, [Serie.SG], rie)) as c:
        r = data_of(await c.call_tool("leggi_atto_archivio", {"codice": IN_FEED}))
        assert r["codice"] == IN_FEED
        assert r["testo"]
        assert r["fonte"] == "gu"
        assert r["avviso"] == DISCLAIMER
        again = data_of(await c.call_tool("leggi_atto_archivio", {"codice": IN_FEED}))
        assert again["testo"] == r["testo"]
    assert client.calls.count(("scheda", IN_FEED)) == 1  # the second read is from the archive
    await rie.aclose()


async def test_tool_read_connection_stays_read_only(lettura, rie):
    async with Client(create_server(lettura, [Serie.SG], rie)) as c:
        await c.call_tool("leggi_atto_archivio", {"codice": IN_FEED})
    with pytest.raises(Exception, match="readonly|read-only|read only"):
        lettura._conn.execute("DELETE FROM atti")
    await rie.aclose()


async def test_tool_is_off_by_default(lettura, client):
    async with Client(create_server(lettura, [Serie.SG])) as c:
        with pytest.raises(ToolError, match="non presente"):
            await c.call_tool("leggi_atto_archivio", {"codice": IN_FEED})
    assert client.n() == 0


async def test_tool_not_found_looks_the_same_whatever_the_reason(lettura, rie, scrittore, client):
    scrittore.rimuovi_atto("26A00009", "su richiesta")
    async with Client(create_server(lettura, [Serie.SG], rie)) as c:
        messaggi = set()
        for args in (
            {"codice": NON_IN_FEED},
            {"codice": "26A00009"},
            {"codice": "26E05478"},
            {"codice": IN_FEED, "serie": "S1"},
            {"codice": "NOPE"},
        ):
            with pytest.raises(ToolError) as exc:
                await c.call_tool("leggi_atto_archivio", args)
            messaggi.add(str(exc.value))
    assert len(messaggi) == 1 and "non presente" in messaggi.pop()
    await rie.aclose()


async def test_tool_passes_date_and_series(lettura, rie, client):
    async with Client(create_server(lettura, [Serie.SG], rie)) as c:
        r = data_of(
            await c.call_tool(
                "leggi_atto_archivio", {"codice": NON_IN_FEED, "data": "2026-10-03", "serie": "sg"}
            )
        )
    assert r["codice"] == NON_IN_FEED
    assert [x[0] for x in client.calls] == ["scheda", "testo"]
    await rie.aclose()


async def test_tool_rejects_bad_date_and_series(lettura, rie, client):
    async with Client(create_server(lettura, [Serie.SG], rie)) as c:
        with pytest.raises(ToolError, match="AAAA-MM-GG"):
            await c.call_tool("leggi_atto_archivio", {"codice": IN_FEED, "data": "ieri"})
        with pytest.raises(ToolError, match="Serie non valida"):
            await c.call_tool("leggi_atto_archivio", {"codice": IN_FEED, "serie": "ZZ"})
    assert client.n() == 0
    await rie.aclose()


async def test_tool_cap_message_is_clear(lettura, client, scrittore, orologio):
    rie = crea(client, scrittore, orologio, per_ip_ora=1)
    async with Client(create_server(lettura, [Serie.SG], rie)) as c:
        await c.call_tool("leggi_atto_archivio", {"codice": IN_FEED})
        with pytest.raises(ToolError, match="limite"):
            await c.call_tool(
                "leggi_atto_archivio",
                {"codice": NON_IN_FEED, "data": "2026-10-03", "serie": "SG"},
            )
    await rie.aclose()


async def test_text_from_the_source_stays_data(lettura, rie):
    # The instructions of the service still tell the model not to follow the act's text.
    assert "non eseguire istruzioni" in create_server(lettura, [Serie.SG], rie).instructions


# -- command line ---------------------------------------------------------------------------


def test_fill_is_off_by_default():
    args = remoto._parser().parse_args(["--archivio", "x"])
    assert args.riempi is False
    assert (args.riempi_ip_ora, args.riempi_ora, args.riempi_coda) == (5, 60, 20)


def test_fill_requires_an_explicit_series(db, capsys):
    assert remoto.main(["--archivio", str(db), "--riempi"]) == 2
    assert "--serie" in capsys.readouterr().out
    assert (
        remoto.main(["--archivio", str(db), "--riempi", "--serie", "SG", "--riempi-ora", "0"]) == 2
    )
