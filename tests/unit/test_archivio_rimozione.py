"""Removal of acts on request: the act goes away and the daily jobs never bring it back."""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from gazzetta_mcp.archivio import ArchiveStore, Arco, NumeroDaFare
from gazzetta_mcp.archivio import store as store_mod
from gazzetta_mcp.archivio.__main__ import main
from gazzetta_mcp.archivio.acquisizione_gu import acquisisci_numero
from gazzetta_mcp.archivio.acquisizione_normattiva import acquisisci_atti_normattiva
from gazzetta_mcp.models import Atto, SearchFilters, Serie
from gazzetta_mcp.parsing import GuParser

from .test_archivio_gu import DAY, ISSUE, N_ACTS, FakeClient
from .test_archivio_normattiva import FakeClient as FakeNormattiva
from .test_archivio_normattiva import _sleep

PAROLA = "zanzibar"


def _atto(codice: str = "26A00001", parola: str = PAROLA) -> Atto:
    return Atto(
        codice=codice,
        serie=Serie.SG,
        data=date(2026, 1, 5),
        titolo=f"Decreto {parola}",
        emettitore="Ministero",
        tipo="decreto",
        testo=f"Il testo riservato parla di {parola}.",
        link=f"https://example.test/{codice}",
        numero_gu=3,
    )


@pytest.fixture
def store():
    with ArchiveStore(":memory:") as s:
        yield s


def _cerca(store: ArchiveStore, testo: str = PAROLA):
    return store.search(testo, SearchFilters())


def test_rimuovi_atto_deletes_row_index_and_arcs(store):
    store.put_atto(_atto("26A00001"), fonte="gu")
    store.put_atto(_atto("26A00002", parola="altro"), fonte="gu")
    store.put_archi(
        [
            Arco("26A00001", "26A00002", "modifica", "gu"),
            Arco("26A00002", "26A00001", "cita", "gu"),
            Arco("26A00002", "26A00003", "cita", "gu"),
        ]
    )
    assert [h.codice for h in _cerca(store)] == ["26A00001"]

    assert store.rimuovi_atto("26A00001", "richiesta dell'interessato") is True

    assert store.get_atto("26A00001") is None
    assert not store.has_atto("26A00001")
    assert _cerca(store) == []
    assert (
        store.read("SELECT COUNT(*) AS n FROM atti_fts WHERE atti_fts MATCH ?", (PAROLA,))[0]["n"]
        == 0
    )
    assert store.read("SELECT COUNT(*) AS n FROM atti_fts")[0]["n"] == 1
    assert store.archi_di("26A00001") == [] and store.archi_di("26A00001", uscenti=False) == []
    assert store.archi_di("26A00002") == [Arco("26A00002", "26A00003", "cita", "gu")]
    assert store.get_atto("26A00002") is not None


def test_rimuovi_atto_keeps_no_text_only_the_code(store):
    store.put_atto(_atto(), fonte="gu")
    store.rimuovi_atto("26A00001", "motivo")
    assert store.e_rimosso("26A00001") and not store.e_rimosso("26A99999")
    [(codice, motivo, quando)] = store.elenco_rimossi()
    assert (codice, motivo) == ("26A00001", "motivo") and quando
    dump = " ".join(str(tuple(r)) for r in store.read("SELECT * FROM rimossi"))
    assert PAROLA not in dump
    assert store.count_rimossi() == 1


def test_rimuovi_atto_not_archived_is_still_recorded(store):
    assert store.rimuovi_atto("26A00009", "preventivo") is False
    assert store.e_rimosso("26A00009")
    assert store.put_atto(_atto("26A00009"), fonte="gu") is False
    assert store.count_atti() == 0


def test_rimuovi_atto_twice_is_harmless(store):
    store.put_atto(_atto(), fonte="gu")
    assert store.rimuovi_atto("26A00001", "primo") is True
    assert store.rimuovi_atto("26A00001", "secondo") is False
    assert store.elenco_rimossi()[0][1] == "primo"


def test_rimuovi_atto_is_one_transaction(store):
    store.put_atto(_atto(), fonte="gu")
    store._conn.execute("DROP TABLE rimossi")  # the last statement of the removal will fail
    with pytest.raises(sqlite3.Error):
        store.rimuovi_atto("26A00001", "x")
    assert store.has_atto("26A00001")
    assert [h.codice for h in _cerca(store)] == ["26A00001"]


def test_removed_code_is_refused_by_put_and_sostituisci(store):
    store.put_atto(_atto(), fonte="normattiva", completo=False)
    store.rimuovi_atto("26A00001", "x")
    assert store.put_atto(_atto(), fonte="gu") is False
    assert store.sostituisci_atto(_atto(), fonte="gu") is False
    assert store.count_atti() == 0 and _cerca(store) == []


def test_sostituisci_is_refused_even_if_a_row_exists(store):
    """Defensive: a removed code with a leftover partial row is not rewritten."""
    store.put_atto(_atto(parola="vecchio"), fonte="normattiva", completo=False)
    store._conn.execute("INSERT INTO rimossi VALUES ('26A00001', 'x', 'oggi')")
    assert store.sostituisci_atto(_atto(), fonte="gu") is False
    assert "vecchio" in store.get_atto("26A00001").titolo


def test_put_archi_ignores_arcs_touching_removed_codes(store):
    store.rimuovi_atto("26A00001", "x")
    nuovi = store.put_archi(
        [
            Arco("26A00001", "26A00002", "cita", "gu"),
            Arco("26A00003", "26A00001", "cita", "gu"),
            Arco("26A00003", "26A00002", "cita", "gu"),
        ]
    )
    assert nuovi == 1
    assert store.archi_di("26A00001") == [] and store.archi_di("26A00001", uscenti=False) == []


def test_compatta_keeps_the_other_acts_and_drops_the_removed_text(tmp_path):
    path = tmp_path / "a.sqlite3"
    with ArchiveStore(path) as s:
        for i in range(30):
            s.put_atto(
                _atto(f"26A{i:05d}", parola=f"parola{i} " + "riempimento " * 500), fonte="gu"
            )
        s.put_atto(_atto("26A99999", parola="qwertyuiop"), fonte="gu")
        s.put_archi([Arco("26A00001", "26A00002", "cita", "gu")])
        s.rimuovi_atto("26A99999", "x")
        s.compatta()
        assert s.count_atti() == 30
        assert _cerca(s, "parola5")[0].codice == "26A00005"
        assert s.archi_di("26A00001")
        assert s.e_rimosso("26A99999")
    for f in tmp_path.iterdir():  # file, -wal and -shm: the removed text is nowhere
        assert b"qwertyuiop" not in f.read_bytes(), f.name
    with ArchiveStore(path) as s:  # still a valid, complete archive
        assert s.count_atti() == 30
        assert s._conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_compatta_on_memory_database_is_harmless(store):
    store.put_atto(_atto(), fonte="gu")
    store.compatta()
    assert store.count_atti() == 1


# -- migration -------------------------------------------------------------------------------


def test_upgrade_from_a_real_v2_file(tmp_path):
    path = tmp_path / "v2.sqlite3"
    conn = sqlite3.connect(path)  # a v2 file built from the real v1 + v2 migrations
    conn.executescript(store_mod._MIGRATIONS[0] + store_mod._MIGRATIONS[1])
    conn.execute("PRAGMA user_version = 2")
    cur = conn.execute(
        "INSERT INTO atti (codice, fonte, serie, data, titolo, emettitore, testo, link,"
        " archiviato_il) VALUES (?,?,?,?,?,?,?,?,?)",
        ("26A00001", "gu", "SG", "2026-01-05", f"Decreto {PAROLA}", "M", PAROLA, "l", "ieri"),
    )
    conn.execute(
        "INSERT INTO atti_fts (rowid, titolo, emettitore, testo) VALUES (?,?,?,?)",
        (cur.lastrowid, f"Decreto {PAROLA}", "M", PAROLA),
    )
    conn.execute("INSERT INTO archi VALUES (?,?,?,?)", ("26A00001", "26A00002", "cita", "gu"))
    conn.commit()
    conn.close()
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'rimossi'").fetchone() is None
    conn.close()

    assert store_mod.SCHEMA_VERSION >= 3
    with ArchiveStore(path) as s:
        assert s._conn.execute("PRAGMA user_version").fetchone()[0] == store_mod.SCHEMA_VERSION
        assert s.count_atti() == 1 and s.count_rimossi() == 0
        assert [h.codice for h in _cerca(s)] == ["26A00001"]
        assert s.rimuovi_atto("26A00001", "x") is True
        assert _cerca(s) == [] and s.archi_di("26A00001") == []


def test_remote_read_only_archive_accepts_the_new_schema(tmp_path):
    from gazzetta_mcp.archivio.remoto import ArchivioSolaLettura

    path = tmp_path / "a.sqlite3"
    with ArchiveStore(path) as s:
        s.put_atto(_atto(), fonte="gu")
    with ArchivioSolaLettura(path) as ro:
        assert ro.get_atto("26A00001") is not None


# -- acquisition -----------------------------------------------------------------------------


async def test_gu_does_not_download_nor_count_a_removed_act(store):
    client = FakeClient()
    store.aggiungi_numeri([(Serie.SG, DAY, ISSUE)])
    store.rimuovi_atto("26A05182", "richiesta")
    nuovi = await acquisisci_numero(
        client, GuParser(), store, NumeroDaFare(Serie.SG, DAY, ISSUE, 0)
    )
    assert nuovi == N_ACTS - 1
    assert client.count("scheda") == client.count("testo") == N_ACTS - 1
    assert ("scheda", "26A05182") not in client.calls
    assert not store.has_atto("26A05182")


async def test_gu_removed_act_stays_away_the_day_after(store):
    client = FakeClient()
    store.aggiungi_numeri([(Serie.SG, DAY, ISSUE)])
    voce = NumeroDaFare(Serie.SG, DAY, ISSUE, 0)
    await acquisisci_numero(client, GuParser(), store, voce)
    assert store.has_atto("26A05182")
    store.rimuovi_atto("26A05182", "richiesta")
    client.calls.clear()
    assert await acquisisci_numero(client, GuParser(), store, voce) == 0
    assert not store.has_atto("26A05182") and _cerca(store, "26A05182") == []
    assert client.count("scheda") == 0


async def test_normattiva_does_not_download_nor_count_a_removed_act(store):
    store.rimuovi_atto("26G00185", "richiesta")
    client = FakeNormattiva()
    n = await acquisisci_atti_normattiva(
        client, store, date(2026, 10, 1), date(2026, 10, 7), max_atti=100, sleep=_sleep
    )
    assert n == 5 and store.count_atti() == 5
    assert client.n("articolo") == 5
    assert not store.has_atto("26G00185")


async def test_normattiva_removed_act_stays_away_after_having_been_archived(store):
    args = (store, date(2026, 10, 1), date(2026, 10, 7))
    await acquisisci_atti_normattiva(FakeNormattiva(), *args, max_atti=100, sleep=_sleep)
    assert store.has_atto("26G00185")
    store.rimuovi_atto("26G00185", "richiesta")
    client = FakeNormattiva()
    assert await acquisisci_atti_normattiva(client, *args, max_atti=100, sleep=_sleep) == 0
    assert client.n("articolo") == 0
    assert not store.has_atto("26G00185")


async def test_removed_acts_do_not_use_up_max_atti(store):
    store.rimuovi_atto("26G00185", "richiesta")
    n = await acquisisci_atti_normattiva(
        FakeNormattiva(), store, date(2026, 10, 1), date(2026, 10, 7), max_atti=2, sleep=_sleep
    )
    assert n == 2 and store.count_atti() == 2


# -- command line ----------------------------------------------------------------------------


@pytest.fixture
def archivio(tmp_path, monkeypatch):
    path = tmp_path / "archivio.sqlite3"
    monkeypatch.setenv("GAZZETTA_MCP_ARCHIVIO_PATH", str(path))
    with ArchiveStore(path) as s:
        s.put_atto(_atto("26A00001"), fonte="gu")
        s.put_atto(_atto("26A00002", parola="altro"), fonte="gu")
    return path


def test_cli_rimuovi_without_si_only_previews(archivio, capsys):
    assert main(["rimuovi", "26A00001", "--motivo", "altro"]) == 0
    out = capsys.readouterr().out
    assert "26A00001" in out and "2026-01-05" in out and "Decreto zanzibar" in out
    assert "--si" in out
    with ArchiveStore(archivio) as s:
        assert s.has_atto("26A00001") and s.count_rimossi() == 0


def test_cli_rimuovi_si_deletes_and_rimossi_lists(archivio, capsys):
    assert (
        main(["rimuovi", "26A00001", "26A00077", "--motivo", "richiesta-interessato", "--si"]) == 0
    )
    capsys.readouterr()
    with ArchiveStore(archivio) as s:
        assert not s.has_atto("26A00001") and s.has_atto("26A00002")
        assert s.e_rimosso("26A00077")
    assert main(["rimossi"]) == 0
    out = capsys.readouterr().out
    assert "26A00001" in out and "26A00077" in out and "richiesta" in out
    assert PAROLA not in out
    assert b"zanzibar" not in archivio.read_bytes()


def test_cli_rimuovi_requires_a_reason(archivio):
    with pytest.raises(SystemExit):
        main(["rimuovi", "26A00001", "--si"])


def test_cli_stato_counts_removed_and_rimossi_needs_no_archive(
    archivio, tmp_path, monkeypatch, capsys
):
    main(["rimuovi", "26A00001", "--motivo", "errore", "--si"])
    capsys.readouterr()
    assert main(["stato"]) == 0
    import json

    out = json.loads(capsys.readouterr().out)
    assert out["atti"] == 1 and out["atti_rimossi"] == 1
    monkeypatch.setenv("GAZZETTA_MCP_ARCHIVIO_PATH", str(tmp_path / "manca" / "a.sqlite3"))
    assert main(["rimossi"]) == 0
    assert not (tmp_path / "manca").exists()


def test_a_reason_with_an_email_or_too_long_is_refused():
    import pytest

    from gazzetta_mcp.archivio import ArchiveStore

    with ArchiveStore(":memory:") as store:
        with pytest.raises(ValueError):
            store.rimuovi_atto("26A00001", "chiesto da mario@example.it")
        with pytest.raises(ValueError):
            store.rimuovi_atto("26A00001", "x" * 200)


def test_compatta_says_so_when_a_reader_keeps_the_old_data_in_the_file(tmp_path, monkeypatch):
    import sqlite3

    import pytest

    from gazzetta_mcp.archivio import ArchiveError, ArchiveStore
    from gazzetta_mcp.archivio import store as store_module

    monkeypatch.setattr(store_module.time, "sleep", lambda s: None)
    path = tmp_path / "a.sqlite3"
    with ArchiveStore(path) as store:
        store.put_atto(_atto("26A00001"), fonte="gu")
        reader = sqlite3.connect(path)
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM atti").fetchone()  # open read transaction
        store.set_stato("x", "y")  # something new in the WAL beyond the reader's snapshot
        store._conn.execute("PRAGMA busy_timeout = 0")  # do not wait 5 s per attempt
        with pytest.raises(ArchiveError, match="Ferma il servizio"):
            store.compatta()
        reader.close()
        store.compatta()  # without the reader it works


def test_rimuovi_refuses_invalid_codes_and_a_missing_archive(tmp_path, monkeypatch, capsys):
    from gazzetta_mcp.archivio.__main__ import main

    monkeypatch.setenv("GAZZETTA_MCP_ARCHIVIO_PATH", str(tmp_path / "manca" / "a.sqlite3"))
    assert main(["rimuovi", "26A00001", "--motivo", "altro", "--si"]) == 1
    assert not (tmp_path / "manca").exists()
