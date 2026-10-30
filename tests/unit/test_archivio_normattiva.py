"""Acquisition from Normattiva: only fixtures and fake clients, no network."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from gazzetta_mcp.archivio import ArchiveStore, Arco
from gazzetta_mcp.archivio.acquisizione_normattiva import (
    CHIAVE_CURSORE,
    CHIAVE_ERRORE,
    NormattivaOpenData,
    PaginaAtti,
    acquisisci_archi_normattiva,
    acquisisci_atti_normattiva,
    aggiorna_normattiva,
    archi_da_normattiva,
    recupera_normattiva,
    urn_da_voce,
)
from gazzetta_mcp.config import Settings
from gazzetta_mcp.models import Atto, Serie
from gazzetta_mcp.sources.gu import GuHttpError
from gazzetta_mcp.sources.normattiva_vigente import VigenteNotFoundError

FIX = Path(__file__).parent.parent / "fixtures" / "normattiva_archivio"
PAG1 = json.loads((FIX / "avanzata_pag1.json").read_text(encoding="utf-8"))
PAG2 = json.loads((FIX / "avanzata_pag2.json").read_text(encoding="utf-8"))
AGGIORNATI = json.loads((FIX / "aggiornati_ottobre.json").read_text(encoding="utf-8"))
ARTICOLO = (FIX / "dettaglio_originale_legge_2026_171.json").read_bytes()
SENZA_SLEEP: list[float] = []


async def _sleep(secondi: float) -> None:
    SENZA_SLEEP.append(secondi)


class FakeClient:
    """In-memory Normattiva: pages of entries, updated entries, one article text for all."""

    def __init__(self, pagine=None, aggiornati=None, errori=None):
        self.pagine = pagine if pagine is not None else [PAG1, PAG2]
        self.aggiornati = aggiornati if aggiornati is not None else AGGIORNATI
        self.errori = errori or {}  # method name -> list of exceptions to raise, in order
        self.chiamate: list[tuple] = []

    def _fail(self, nome):
        coda = self.errori.get(nome)
        if coda:
            exc = coda.pop(0)
            if exc is not None:
                raise exc

    async def elenca_atti(self, dal, al, pagina):
        self.chiamate.append(("elenca", dal, al, pagina))
        self._fail("elenca")
        d = self.pagine[pagina - 1]
        return PaginaAtti(d["listaAtti"], len(self.pagine))

    async def atti_aggiornati(self, dal, al):
        self.chiamate.append(("aggiornati", dal, al))
        self._fail("aggiornati")
        return self.aggiornati["listaAtti"]

    async def get_articolo(self, urn):
        self.chiamate.append(("articolo", urn))
        self._fail("articolo")
        return ARTICOLO

    def n(self, nome):
        return sum(1 for c in self.chiamate if c[0] == nome)


@pytest.fixture(autouse=True)
def _reset():
    SENZA_SLEEP.clear()


@pytest.fixture
def store():
    with ArchiveStore(":memory:") as s:
        yield s


def _gu_atto(codice: str) -> Atto:
    return Atto(
        codice=codice,
        serie=Serie.SG,
        data=date(2026, 10, 1),
        titolo="Dalla GU",
        emettitore="Parlamento",
        tipo="LEGGE",
        testo="Testo GU",
        link="https://gu.test/x",
    )


# -- pure functions --------------------------------------------------------------------------


def test_urn_da_voce_builds_the_urn_of_each_type():
    urns = [urn_da_voce(v) for v in PAG1["listaAtti"] + PAG2["listaAtti"]]
    assert urns == [
        "urn:nir:stato:legge:2026-09-23;171",
        "urn:nir:stato:decreto.legislativo:2026-09-11;172",
        "urn:nir:stato:legge:2026-10-05;174",
        "urn:nir:stato:legge:2026-10-05;173",
        "urn:nir:stato:decreto.legislativo:2026-09-25;176",
        "urn:nir:stato:legge:2026-10-05;175",
    ]


def test_urn_da_voce_handles_hyphen_and_missing_fields():
    voce = {
        "denominazioneAtto": "DECRETO-LEGGE",
        "annoProvvedimento": "2026",
        "meseProvvedimento": "8",
        "giornoProvvedimento": "7",
        "numeroProvvedimento": "144",
    }
    assert urn_da_voce(voce) == "urn:nir:stato:decreto.legge:2026-08-07;144"
    assert urn_da_voce({**voce, "annoProvvedimento": None}) is None
    assert urn_da_voce({**voce, "numeroProvvedimento": "", "numeroAtto": ""}) is None


def test_archi_da_normattiva_one_arc_per_modifying_code():
    voci = [
        {"codiceRedazionale": "24G00028", "ultimiAttiModificanti": "24A02106 24A02107"},
        {"codiceRedazionale": "24G00029", "ultimiAttiModificanti": None},
        {"codiceRedazionale": "24G00030", "ultimiAttiModificanti": "24G00030"},
        {"codiceRedazionale": "", "ultimiAttiModificanti": "24A00001"},
    ]
    assert archi_da_normattiva(voci) == [
        Arco("24A02106", "24G00028", "modifica", "normattiva"),
        Arco("24A02107", "24G00028", "modifica", "normattiva"),
    ]


def test_archi_da_normattiva_on_the_real_sample():
    archi = archi_da_normattiva(AGGIORNATI["listaAtti"])
    assert Arco("26G00194", "26G00167", "modifica", "normattiva") in archi
    assert all(a.fonte == "normattiva" and a.tipo == "modifica" for a in archi)


# -- acquisition -----------------------------------------------------------------------------


async def test_acquisisci_stores_every_act_with_the_gu_code(store):
    client = FakeClient()
    n = await acquisisci_atti_normattiva(
        client, store, date(2026, 10, 1), date(2026, 10, 7), max_atti=100, sleep=_sleep
    )
    assert n == 6
    assert store.count_atti() == 6
    atto = store.get_atto("26G00185")
    assert atto.titolo.startswith("LEGGE 23 settembre 2026, n. 171: Proroga")
    assert atto.data == date(2026, 10, 1)
    assert atto.numero_gu == 228
    assert atto.tipo == "LEGGE"
    assert "Promulga" in atto.testo and "Art. 1" in atto.testo
    assert atto.link.endswith("/uri-res/N2Ls?urn:nir:stato:legge:2026-09-23;171")
    assert store.codice_da_urn("urn:nir:stato:legge:2026-09-23;171") == "26G00185"
    assert client.n("articolo") == 6
    assert ("articolo", "urn:nir:stato:legge:2026-09-23;171@originale") in client.chiamate
    assert store.get_stato(CHIAVE_ERRORE) == ""


async def test_acquisisci_does_not_overwrite_the_gu_act_and_records_the_urn(store):
    store.put_atto(_gu_atto("26G00185"), fonte="gu")
    client = FakeClient()
    n = await acquisisci_atti_normattiva(
        client, store, date(2026, 10, 1), date(2026, 10, 7), max_atti=100, sleep=_sleep
    )
    assert n == 5
    assert client.n("articolo") == 5  # nothing downloaded for the act already archived
    atto = store.get_atto("26G00185")
    assert atto.titolo == "Dalla GU" and atto.testo == "Testo GU"
    assert store.codice_da_urn("urn:nir:stato:legge:2026-09-23;171") == "26G00185"


async def test_acquisisci_is_idempotent(store):
    args = (store, date(2026, 10, 1), date(2026, 10, 7))
    await acquisisci_atti_normattiva(FakeClient(), *args, max_atti=100, sleep=_sleep)
    second = FakeClient()
    n = await acquisisci_atti_normattiva(second, *args, max_atti=100, sleep=_sleep)
    assert n == 0
    assert second.n("articolo") == 0


async def test_acquisisci_respects_max_atti(store):
    client = FakeClient()
    n = await acquisisci_atti_normattiva(
        client, store, date(2026, 10, 1), date(2026, 10, 7), max_atti=2, sleep=_sleep
    )
    assert n == 2 and store.count_atti() == 2
    assert client.n("elenca") == 1  # does not even ask for the next page


async def test_acquisisci_keeps_title_when_the_article_is_missing(store):
    client = FakeClient(errori={"articolo": [VigenteNotFoundError("404")]})
    await acquisisci_atti_normattiva(
        client, store, date(2026, 10, 1), date(2026, 10, 7), max_atti=1, sleep=_sleep
    )
    atto = store.get_atto("26G00185")
    assert atto is not None and atto.testo == ""


async def test_acquisisci_backs_off_then_stops_on_http_errors(store):
    boom = GuHttpError("Normattiva list: HTTP status 429")
    client = FakeClient(errori={"elenca": [boom, boom, boom, boom]})
    n = await acquisisci_atti_normattiva(
        client, store, date(2026, 10, 1), date(2026, 10, 7), max_atti=100, sleep=_sleep
    )
    assert n == 0
    assert client.n("elenca") == 3  # first try plus two retries, then it gives up
    assert SENZA_SLEEP == [30.0, 120.0]
    assert "429" in store.get_stato(CHIAVE_ERRORE)


async def test_acquisisci_recovers_after_one_failure(store):
    boom = GuHttpError("HTTP status 503")
    client = FakeClient(errori={"elenca": [boom]})
    n = await acquisisci_atti_normattiva(
        client, store, date(2026, 10, 1), date(2026, 10, 7), max_atti=100, sleep=_sleep
    )
    assert n == 6 and SENZA_SLEEP == [30.0]


async def test_acquisisci_keeps_the_acts_stored_before_a_stop(store):
    boom = GuHttpError("HTTP status 500")
    # the 3rd article request fails every time
    client = FakeClient(errori={"articolo": [None, None, boom, boom, boom]})
    n = await acquisisci_atti_normattiva(
        client, store, date(2026, 10, 1), date(2026, 10, 7), max_atti=100, sleep=_sleep
    )
    assert n == 2 and store.count_atti() == 2
    assert "500" in store.get_stato(CHIAVE_ERRORE)


# -- relations -------------------------------------------------------------------------------


async def test_acquisisci_archi_saves_the_relations(store):
    client = FakeClient()
    n = await acquisisci_archi_normattiva(
        client, store, date(2026, 10, 1), date(2026, 10, 30), sleep=_sleep
    )
    assert n >= 5
    assert store.archi_di("26G00194", uscenti=True)[0].fonte == "normattiva"
    again = await acquisisci_archi_normattiva(
        client, store, date(2026, 10, 1), date(2026, 10, 30), sleep=_sleep
    )
    assert again == 0


async def test_acquisisci_archi_stops_quietly_on_errors(store):
    boom = GuHttpError("HTTP status 429")
    client = FakeClient(errori={"aggiornati": [boom, boom, boom]})
    n = await acquisisci_archi_normattiva(
        client, store, date(2026, 10, 1), date(2026, 10, 30), sleep=_sleep
    )
    assert n == 0 and "429" in store.get_stato(CHIAVE_ERRORE)


# -- daily update and recovery ---------------------------------------------------------------


async def test_aggiorna_window_acts_and_relations(store):
    client = FakeClient()
    n = await aggiorna_normattiva(
        client, store, giorni=7, oggi=lambda: date(2026, 10, 8), sleep=_sleep
    )
    assert ("elenca", date(2026, 10, 1), date(2026, 10, 8), 1) in client.chiamate
    assert ("aggiornati", date(2026, 10, 1), date(2026, 10, 8)) in client.chiamate
    # the 6 published acts plus the changed ones not archived yet
    assert n == store.count_atti() > 6
    assert store.archi_di("26G00167", uscenti=False)[0].da == "26G00194"


async def test_aggiorna_stops_at_max_atti(store):
    n = await aggiorna_normattiva(
        FakeClient(), store, max_atti=3, oggi=lambda: date(2026, 10, 8), sleep=_sleep
    )
    assert n == 3 and store.count_atti() == 3


async def test_recupera_moves_the_cursor_backward_and_resumes(store):
    oggi = lambda: date(2026, 10, 8)
    client = FakeClient(pagine=[PAG2])  # same answer for every window
    n = await recupera_normattiva(
        client, store, max_atti=1000, finestra_giorni=7, fino_a=date(2026, 9, 20),
        oggi=oggi, sleep=_sleep,
    )  # fmt: skip
    # windows: 10-02..10-08, 09-25..10-01, 09-20..09-24 (the limit)
    finestre = [(c[1], c[2]) for c in client.chiamate if c[0] == "elenca"]
    assert finestre == [
        (date(2026, 10, 2), date(2026, 10, 8)),
        (date(2026, 9, 25), date(2026, 10, 1)),
        (date(2026, 9, 20), date(2026, 9, 24)),
    ]
    assert n == 2  # same two acts every time: archived once
    assert store.get_stato(CHIAVE_CURSORE) == "2026-09-20"

    second = FakeClient(pagine=[PAG2])
    assert (
        await recupera_normattiva(
            second, store, max_atti=10, fino_a=date(2026, 9, 20), oggi=oggi, sleep=_sleep
        )
        == 0
    )
    assert second.chiamate == []  # nothing left to do


async def test_recupera_does_not_move_the_cursor_when_interrupted(store):
    boom = GuHttpError("HTTP status 503")
    client = FakeClient(pagine=[PAG2], errori={"elenca": [None, boom, boom, boom]})
    n = await recupera_normattiva(
        client, store, max_atti=100, finestra_giorni=7, fino_a=date(2026, 1, 1),
        oggi=lambda: date(2026, 10, 8), sleep=_sleep,
    )  # fmt: skip
    assert n == 2  # first window done, second window stopped
    assert store.get_stato(CHIAVE_CURSORE) == "2026-10-02"
    assert "503" in store.get_stato(CHIAVE_ERRORE)


async def test_recupera_does_not_move_the_cursor_when_max_atti_is_reached(store):
    client = FakeClient(pagine=[PAG1, PAG2])
    n = await recupera_normattiva(
        client, store, max_atti=2, oggi=lambda: date(2026, 10, 8), sleep=_sleep
    )
    assert n == 2
    assert store.get_stato(CHIAVE_CURSORE) is None


# -- the real client, on a fake transport ----------------------------------------------------


def _transport(seen: list[httpx.Request], status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if status != 200:
            return httpx.Response(status)
        if path.endswith("/ricerca/avanzata"):
            return httpx.Response(200, json=PAG1)
        if path.endswith("/ricerca/aggiornati"):
            return httpx.Response(200, json=AGGIORNATI)
        return httpx.Response(200, content=ARTICOLO)

    return httpx.MockTransport(handler)


class _Limiter:
    def __init__(self):
        self.n = 0

    async def acquire(self):
        self.n += 1


async def test_open_data_client_builds_the_requests_and_uses_the_limiter():
    seen: list[httpx.Request] = []
    limiter = _Limiter()
    client = NormattivaOpenData(Settings(), transport=_transport(seen), limiter=limiter)
    try:
        pagina = await client.elenca_atti(date(2026, 10, 1), date(2026, 10, 7), 2)
        aggiornati = await client.atti_aggiornati(date(2026, 10, 1), date(2026, 10, 30))
        articolo = await client.get_articolo("urn:nir:stato:legge:2026-09-23;171@originale")
    finally:
        await client.aclose()
    assert pagina.pagine == 2 and len(pagina.voci) == 4
    assert len(aggiornati) == 5 and articolo == ARTICOLO
    avanzata = json.loads(seen[0].content)
    assert avanzata["dataInizioPubProvvedimento"] == "2026-10-01"
    assert avanzata["dataFinePubProvvedimento"] == "2026-10-07"
    assert avanzata["paginazione"]["paginaCorrente"] == 2
    agg = json.loads(seen[1].content)
    assert agg["dataInizioAggiornamento"] == "2026-10-01T00:00:00.000Z"
    assert agg["dataFineAggiornamento"] == "2026-10-30T23:59:59.999Z"
    assert json.loads(seen[2].content) == {"urn": "urn:nir:stato:legge:2026-09-23;171@originale"}
    assert limiter.n == 3  # every request went through the shared limiter
    assert all("gazzetta-mcp" in r.headers["user-agent"] for r in seen)


async def test_open_data_client_raises_on_429():
    seen: list[httpx.Request] = []
    client = NormattivaOpenData(Settings(), transport=_transport(seen, 429), limiter=_Limiter())
    try:
        with pytest.raises(GuHttpError, match="429"):
            await client.elenca_atti(date(2026, 10, 1), date(2026, 10, 7), 1)
    finally:
        await client.aclose()
    assert len(seen) == 1  # no retry inside the client
