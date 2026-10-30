from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from gazzetta_mcp.archivio import ArchiveStore, Arco
from gazzetta_mcp.models import Atto, SearchFilters, Serie


def _atto(codice: str = "26A00001", titolo: str = "Decreto sugli appalti pubblici") -> Atto:
    return Atto(
        codice=codice,
        serie=Serie.SG,
        data=date(2026, 1, 5),
        titolo=titolo,
        emettitore="Ministero",
        tipo="decreto",
        testo="Testo dell'atto sugli acquisti della scuola.",
        link=f"https://example.test/{codice}",
        numero_gu=3,
    )


@pytest.fixture
def store():
    with ArchiveStore(":memory:") as s:
        yield s


def test_put_atto_is_immutable(store):
    assert store.put_atto(_atto(), fonte="gu") is True
    assert store.put_atto(_atto(titolo="Cambiato"), fonte="normattiva") is False
    assert store.get_atto("26A00001").titolo == "Decreto sugli appalti pubblici"
    assert store.count_atti() == 1


def test_put_atto_rejects_unknown_source(store):
    with pytest.raises(ValueError):
        store.put_atto(_atto(), fonte="altro")


def test_search_finds_by_stem_and_filters(store):
    store.put_atto(_atto(), fonte="gu")
    hits = store.search("acquisto scuola", SearchFilters())
    assert [h.codice for h in hits] == ["26A00001"]
    assert hits[0].origine == "archivio"
    assert store.search("acquisto", SearchFilters(dal=date(2027, 1, 1))) == []
    assert store.search("acquisto", SearchFilters(serie=Serie.S4)) == []


def test_urn_links_the_two_sources(store):
    store.put_atto(_atto(), fonte="gu")
    assert store.codice_da_urn("urn:x") is None
    store.set_urn("26A00001", "urn:x")
    assert store.codice_da_urn("urn:x") == "26A00001"


def test_queue_goes_backward_and_retries_errors(store):
    store.aggiungi_numeri([(Serie.SG, date(2026, 1, d), None) for d in (3, 4, 5)])
    assert store.aggiungi_numeri([(Serie.SG, date(2026, 1, 5), 7)]) == 0
    todo = store.prossimi_numeri(Serie.SG, 10)
    assert [n.data.day for n in todo] == [5, 4, 3]
    assert todo[0].numero == 7  # a missing number is filled in later
    store.segna_numero(Serie.SG, date(2026, 1, 5), "fatto")
    store.segna_numero(Serie.SG, date(2026, 1, 4), "errore", "429")
    todo = store.prossimi_numeri(Serie.SG, 10)
    assert [(n.data.day, n.tentativi) for n in todo] == [(4, 1), (3, 0)]
    assert store.prossimi_numeri(Serie.SG, 10, max_tentativi=1) == [
        n for n in todo if n.data.day == 3
    ]
    assert store.conteggio_numeri(Serie.SG) == {"fatto": 1, "errore": 1, "da_fare": 1}


def test_segna_numero_rejects_unknown_state(store):
    with pytest.raises(ValueError):
        store.segna_numero(Serie.SG, date(2026, 1, 1), "boh")


def test_archi_are_deduplicated_and_directional(store):
    a = Arco("A", "B", "modifica", "normattiva")
    assert store.put_archi([a, a, Arco("C", "B", "abroga", "gu")]) == 2
    assert store.archi_di("A") == [a]
    assert {x.da for x in store.archi_di("B", uscenti=False)} == {"A", "C"}
    with pytest.raises(ValueError):
        store.put_archi([Arco("A", "B", "inventato", "gu")])


def test_read_is_read_only(store):
    with pytest.raises(ValueError):
        store.read("DELETE FROM atti")
    assert store.read("SELECT COUNT(*) AS n FROM atti")[0]["n"] == 0


def test_stato_notes_are_overwritten(store):
    assert store.get_stato("k") is None
    store.set_stato("k", "1")
    store.set_stato("k", "2")
    assert store.get_stato("k") == "2"


def test_schema_persists_on_disk(tmp_path):
    path = tmp_path / "sub" / "archivio.sqlite3"
    with ArchiveStore(path) as s:
        s.put_atto(_atto(), fonte="gu")
    with ArchiveStore(path) as s:
        assert s.has_atto("26A00001")


def test_partial_text_can_be_replaced_but_a_full_one_never(store):
    parziale = _atto()
    assert store.put_atto(parziale, fonte="normattiva", completo=False) is True
    assert store.ha_testo_completo("26A00001") is False
    intero = Atto(**{**parziale.__dict__, "testo": "Testo intero con articoli sulla pesca."})
    assert store.sostituisci_atto(intero, fonte="gu") is True
    assert store.ha_testo_completo("26A00001")
    assert [h.codice for h in store.search("pesca", SearchFilters())] == ["26A00001"]
    assert store.search("acquisti", SearchFilters()) == []  # the old text left the index
    assert store.sostituisci_atto(parziale, fonte="normattiva") is False  # full text is kept


def test_empty_text_counts_as_not_complete(store):
    store.put_atto(Atto(**{**_atto().__dict__, "testo": ""}), fonte="gu")
    assert store.ha_testo_completo("26A00001") is False


def test_read_cannot_write_even_through_with(store):
    store.put_archi([Arco("A", "B", "modifica", "gu")])
    with pytest.raises(sqlite3.Error):
        store.read("WITH x AS (SELECT 1) DELETE FROM archi")
    assert len(store.archi_di("A")) == 1


def test_not_a_database_is_an_archive_error(tmp_path):
    from gazzetta_mcp.archivio import ArchiveError

    bad = tmp_path / "archivio.sqlite3"
    bad.write_text("questo non e' un database sqlite" * 50)
    with pytest.raises(ArchiveError):
        ArchiveStore(bad)


def test_codici_da_urn_breve_matches_type_year_and_number(store):
    for codice, urn in (
        ("A", "urn:nir:stato:decreto.legislativo:2001-03-30;165"),
        ("B", "urn:nir:stato:decreto.legislativo:2001-03-30;1650"),
        ("C", "urn:nir:stato:decreto.legislativo:2002-03-30;165"),
        ("D", "urn:nir:stato:legge:2001-03-30;165"),
        ("E", "urn:nir:stato:decreto.legislativo:2001;165"),
    ):
        store.put_atto(_atto(codice), fonte="gu", urn=urn)
    assert store.codici_da_urn_breve("decreto.legislativo", 2001, 165) == ["A"]
    assert store.codici_da_urn_breve("decreto.legislativo", "2001", "1650") == ["B"]
    assert store.codici_da_urn_breve("legge", 1999, 1) == []


def test_search_is_fast_on_very_long_texts_and_caps_the_words(store):
    import time

    lungo = Atto(**{**_atto().__dict__, "codice": "26A09999", "testo": "pesca scuola " * 60_000})
    store.put_atto(lungo, fonte="gu")
    inizio = time.monotonic()
    hits = store.search("pesca scuola " * 40 + "parolainesistente", SearchFilters())
    assert hits and hits[0].estratto.endswith("...")
    assert time.monotonic() - inizio < 3  # it took many seconds before the cut-offs
