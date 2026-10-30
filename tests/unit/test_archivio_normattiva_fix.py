"""Normattiva acquisition fixes: partial texts, cursor safety, validation, window cap."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from gazzetta_mcp.archivio import ArchiveStore
from gazzetta_mcp.archivio.acquisizione_normattiva import (
    CHIAVE_CURSORE,
    CHIAVE_ERRORE,
    CHIAVE_LICENZA,
    CHIAVE_SCARTATE,
    NormattivaOpenData,
    PaginaAtti,
    acquisisci_atti_normattiva,
    recupera_normattiva,
    urn_da_voce,
)
from gazzetta_mcp.config import Settings
from gazzetta_mcp.sources.gu import GuError
from gazzetta_mcp.sources.normattiva_vigente import VigenteNotFoundError

FIX = Path(__file__).parent.parent / "fixtures" / "normattiva_archivio"
PAG2 = json.loads((FIX / "avanzata_pag2.json").read_text(encoding="utf-8"))
ARTICOLO = (FIX / "dettaglio_originale_legge_2026_171.json").read_bytes()


async def _sleep(secondi: float) -> None:
    pass


class Fake:
    def __init__(self, voci=None, errore=None, articolo_errore=None):
        self.voci = PAG2["listaAtti"] if voci is None else voci
        self.errore = errore
        self.articolo_errore = articolo_errore
        self.finestre = 0

    async def elenca_atti(self, dal, al, pagina):
        self.finestre += 1
        if self.errore:
            raise self.errore
        return PaginaAtti(self.voci, 1)

    async def atti_aggiornati(self, dal, al):
        return []

    async def get_articolo(self, urn):
        if self.articolo_errore:
            raise self.articolo_errore
        return ARTICOLO


@pytest.fixture
def store():
    with ArchiveStore(":memory:") as s:
        yield s


async def test_new_acts_are_partial_and_never_empty(store):
    await acquisisci_atti_normattiva(
        Fake(), store, date(2026, 10, 1), date(2026, 10, 7), max_atti=10, sleep=_sleep
    )
    codice = PAG2["listaAtti"][0]["codiceRedazionale"]
    assert store.has_atto(codice) and not store.ha_testo_completo(codice)
    assert store.get_stato(CHIAVE_LICENZA).startswith("CC BY 4.0")


async def test_missing_article_stores_title_as_partial_text(store):
    client = Fake(articolo_errore=VigenteNotFoundError("HTTP status 400"))
    await acquisisci_atti_normattiva(
        client, store, date(2026, 10, 1), date(2026, 10, 7), max_atti=10, sleep=_sleep
    )
    atto = store.get_atto(PAG2["listaAtti"][0]["codiceRedazionale"])
    assert atto.testo and atto.testo == atto.titolo
    assert not store.ha_testo_completo(atto.codice)


async def test_non_http_error_suspends_without_advancing_the_cursor(store):
    client = Fake(errore=GuError("Normattiva list: unreadable answer"))
    n = await recupera_normattiva(
        client, store, max_atti=10, oggi=lambda: date(2026, 10, 8), sleep=_sleep
    )
    assert n == 0 and store.get_stato(CHIAVE_CURSORE) is None
    assert "unreadable" in store.get_stato(CHIAVE_ERRORE)


async def test_invalid_entries_are_dropped_and_counted(store):
    bad = {**PAG2["listaAtti"][0], "numeroProvvedimento": "1/../x", "codiceRedazionale": "X1"}
    ok = PAG2["listaAtti"][1]
    n = await acquisisci_atti_normattiva(
        Fake(voci=[bad, ok]), store, date(2026, 10, 1), date(2026, 10, 7),
        max_atti=10, sleep=_sleep,
    )  # fmt: skip
    assert n == 1 and store.get_stato(CHIAVE_SCARTATE) == "1"


def test_urn_da_voce_rejects_odd_remote_fields():
    voce = {
        "denominazioneAtto": "LEGGE",
        "annoProvvedimento": "2026",
        "meseProvvedimento": "8",
        "giornoProvvedimento": "7",
        "numeroProvvedimento": "144",
    }
    assert urn_da_voce(voce) is not None
    assert urn_da_voce({**voce, "denominazioneAtto": "legge;x/../"}) is None
    assert urn_da_voce({**voce, "numeroProvvedimento": "1 2"}) is None
    assert urn_da_voce({**voce, "numeroProvvedimento": "144-bis"}) is not None


async def test_max_finestre_caps_the_windows_per_run(store):
    client = Fake(voci=[])
    await recupera_normattiva(
        client, store, max_atti=10, max_finestre=3, oggi=lambda: date(2026, 10, 8), sleep=_sleep
    )
    assert client.finestre == 3
    assert store.get_stato(CHIAVE_CURSORE) == "2026-09-18"


# -- the real client against odd answers ------------------------------------------------------


def _client(handler):
    return NormattivaOpenData(Settings(), transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "corpo",
    [
        {"listaAtti": None},
        {"message": "errore interno"},
        {"numeroAttiTrovati": 3},
        {"listaAtti": [], "message": "boom"},
    ],
)
async def test_suspicious_answer_is_not_an_empty_window(corpo):
    client = _client(lambda r: httpx.Response(200, json=corpo))
    try:
        with pytest.raises(GuError):
            await client.elenca_atti(date(2026, 10, 1), date(2026, 10, 7), 1)
    finally:
        await client.aclose()


async def test_declared_empty_window_is_valid():
    corpo = {"listaAtti": None, "numeroAttiTrovati": 0, "message": None}
    client = _client(lambda r: httpx.Response(200, json=corpo))
    try:
        pagina = await client.elenca_atti(date(2026, 10, 1), date(2026, 10, 7), 1)
    finally:
        await client.aclose()
    assert pagina.voci == []


async def test_non_json_answer_suspends_the_run(store):
    client = _client(lambda r: httpx.Response(200, content=b"<html>manutenzione</html>"))
    try:
        n = await recupera_normattiva(
            client, store, max_atti=10, oggi=lambda: date(2026, 10, 8), sleep=_sleep
        )
    finally:
        await client.aclose()
    assert n == 0 and store.get_stato(CHIAVE_CURSORE) is None
    assert "unreadable" in store.get_stato(CHIAVE_ERRORE)


def test_empty_list_with_acts_found_is_an_error():
    import pytest

    from gazzetta_mcp.archivio.acquisizione_normattiva import _lista
    from gazzetta_mcp.sources.gu import GuError

    assert _lista({"listaAtti": [], "numeroAttiTrovati": 0}) == []
    assert _lista({"listaAtti": []}) == []
    with pytest.raises(GuError):
        _lista({"listaAtti": [], "numeroAttiTrovati": 12})


def test_long_denominations_are_accepted():
    from gazzetta_mcp.archivio.acquisizione_normattiva import _RE_TIPO

    nome = "decreto del presidente del consiglio dei ministri"
    assert _RE_TIPO.fullmatch(nome)
