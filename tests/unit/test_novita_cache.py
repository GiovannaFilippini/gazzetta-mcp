"""Schema v3 (novita_controlli): migration from an old cache and the memory itself."""

import sqlite3
from datetime import date, datetime, timezone

from gazzetta_mcp.cache import sqlite as mod
from gazzetta_mcp.cache.sqlite import Controllo, SqliteCache
from gazzetta_mcp.models import Atto, Serie

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


def _controllo(**kw) -> Controllo:
    base = dict(  # noqa: C408
        chiave="appalt|",
        argomento="Appalti",
        serie="",
        coperto_fino=date(2026, 10, 2),
        codici=frozenset({"26A00002", "26A00001"}),
        controllato_il=T0,
    )
    base.update(kw)
    return Controllo(**base)


def test_upgrade_from_v2_keeps_existing_data(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    with monkeypatch.context() as m:  # build a cache as the previous version left it
        m.setattr(mod, "_MIGRATIONS", mod._MIGRATIONS[:2])
        with SqliteCache(path) as c:
            assert c.schema_version == 2
            c.put_atto(
                Atto(
                    codice="25A00001",
                    serie=Serie.SG,
                    data=date(2026, 1, 5),
                    titolo="Disposizioni sugli appalti",
                    emettitore="Presidenza",
                    tipo="DECRETO",
                    testo="Art. 1.",
                    link="https://example.test/a",
                )
            )
    conn = sqlite3.connect(path)
    assert (
        conn.execute("SELECT name FROM sqlite_master WHERE name='novita_controlli'").fetchone()
        is None
    )
    conn.close()
    with SqliteCache(path) as c:
        assert c.schema_version == 3
        assert c.get_atto("25A00001").titolo == "Disposizioni sugli appalti"
        assert c.stats()["atti"] == 1 and c.stats()["search_entries"] == 1
        assert c.get_controllo("appalt|") is None
    with SqliteCache(path) as c:  # re-opening does not re-run it
        assert c.schema_version == 3


def test_new_cache_is_at_the_latest_schema():
    with SqliteCache(":memory:") as c:
        assert c.schema_version == len(mod._MIGRATIONS) >= 3


def test_controllo_roundtrip_and_replace(tmp_path):
    path = tmp_path / "c.db"
    with SqliteCache(path) as c:
        c.put_controllo(_controllo())
    with SqliteCache(path) as c:
        assert c.get_controllo("appalt|") == _controllo()
        c.put_controllo(_controllo(coperto_fino=date(2026, 10, 3), codici=frozenset()))
        assert c.get_controllo("appalt|").coperto_fino == date(2026, 10, 3)
        assert c.get_controllo("altro|") is None
        c.delete_controllo("appalt|")
        assert c.get_controllo("appalt|") is None


def test_undo_by_hand_is_harmless(tmp_path):
    """The documented way back: drop the table and set user_version = 2."""
    path = tmp_path / "u.db"
    with SqliteCache(path) as c:
        c.put_controllo(_controllo())
    conn = sqlite3.connect(path)
    conn.executescript("DROP TABLE novita_controlli; PRAGMA user_version = 2;")
    conn.close()
    with SqliteCache(path) as c:  # reopening with the new version recreates the table
        assert c.schema_version == 3
        assert c.get_controllo("appalt|") is None


def test_clear_keeps_the_memory_of_the_checks():
    with SqliteCache(":memory:") as c:
        c.put_controllo(_controllo())
        c.clear()
        assert c.get_controllo("appalt|") is not None
