import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from gazzetta_mcp.cache import CacheError, SqliteCache, build_match_query
from gazzetta_mcp.config import Settings
from gazzetta_mcp.interfaces import Cache
from gazzetta_mcp.models import (
    Atto,
    Feed,
    FeedItem,
    RawPage,
    SearchFilters,
    Serie,
    Sommario,
    SommarioVoce,
)

T0 = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def cache(tmp_path: Path, clock: FakeClock):
    c = SqliteCache(tmp_path / "sub" / "dir" / "cache.sqlite3", clock=clock)
    yield c
    c.close()


def make_atto(codice="25A00001", **kw) -> Atto:
    base: dict = dict(  # noqa: C408
        codice=codice,
        serie=Serie.SG,
        data=date(2026, 1, 5),
        titolo="Disposizioni urgenti per la citta di Roma",
        emettitore="Presidenza del Consiglio dei ministri",
        tipo="DECRETO",
        testo="Art. 1. Il presente decreto disciplina i trasporti pubblici.",
        link=f"https://example.test/atto/{codice}",
        numero_gu=3,
        scaricato_il=T0,
    )
    base.update(kw)
    return Atto(**base)


def hits(cache, text, **filters):
    return cache.search(text, SearchFilters(**filters))


def test_implements_protocol(cache):
    c: Cache = cache
    assert c is cache


def test_from_settings_and_memory(tmp_path):
    with SqliteCache.from_settings(Settings(cache_path=tmp_path / "a" / "c.db")) as c:
        assert c.schema_version == 1
    assert (tmp_path / "a" / "c.db").exists()
    with SqliteCache(":memory:") as m:
        m.put_atto(make_atto())
        assert m.get_atto("25A00001") is not None


def test_http_roundtrip_and_ttl(cache, clock):
    page = RawPage("https://x.test/a", b"\x00\xffbytes", "text/html", clock.now)
    assert cache.get_http(page.url, 60) is None
    cache.put_http(page)
    got = cache.get_http(page.url, 60)
    assert got is not None
    assert got.content == page.content
    assert got.content_type == "text/html"
    assert got.fetched_at == page.fetched_at
    assert got.from_cache is True
    clock.advance(60)
    assert cache.get_http(page.url, 60) is not None
    clock.advance(1)
    assert cache.get_http(page.url, 60) is None
    # replace refreshes the entry
    cache.put_http(RawPage(page.url, b"new", "text/plain", clock.now))
    assert cache.get_http(page.url, 60).content == b"new"


def test_http_naive_datetime_treated_as_utc(cache, clock):
    cache.put_http(RawPage("u", b"x", "t", datetime(2026, 1, 10, 12, 0)))  # noqa: DTZ001
    assert cache.get_http("u", 10) is not None


def make_feed(n=2) -> Feed:
    items = [
        FeedItem(
            codice=f"26A0000{i}",
            serie=Serie.SG,
            data=date(2026, 1, 9),
            titolo=f"Titolo feed {i} agricoltura",
            riassunto=f"Riassunto {i}",
            link=f"https://example.test/f/{i}",
            pubblicato=T0 if i % 2 == 0 else None,
        )
        for i in range(n)
    ]
    return Feed(Serie.SG, 7, date(2026, 1, 9), "https://example.test/gu", items)


def test_feed_roundtrip_order_and_ttl(cache, clock):
    assert cache.get_feed(Serie.SG, 900) is None
    feed = make_feed(3)
    cache.put_feed(feed)
    assert cache.get_feed(Serie.SG, 900) == feed
    assert cache.get_feed(Serie.S4, 900) is None
    clock.advance(901)
    assert cache.get_feed(Serie.SG, 900) is None
    assert cache.get_feed(Serie.SG, 10_000) == feed


def test_feed_replace_drops_old_items(cache):
    cache.put_feed(make_feed(3))
    cache.put_feed(make_feed(1))
    assert len(cache.get_feed(Serie.SG, 900).items) == 1


def make_sommario(day=date(2026, 1, 5)) -> Sommario:
    voci = [
        SommarioVoce(
            "25A00010", "Legge sul mare", "Ministero della giustizia", "Leggi", "l1", "LEGGE"
        ),
        SommarioVoce("25A00011", "Avviso senza tipo", "Regione Lazio", "Avvisi", "l2"),
    ]
    return Sommario(Serie.SG, day, 4, "https://example.test/s", "https://example.test/s.pdf", voci)


def test_sommario_roundtrip(cache):
    assert cache.get_sommario(date(2026, 1, 5), Serie.SG) is None
    s = make_sommario()
    cache.put_sommario(s)
    assert cache.get_sommario(date(2026, 1, 5), Serie.SG) == s
    assert cache.get_sommario(date(2026, 1, 5), Serie.S4) is None
    assert cache.get_sommario(date(2026, 1, 6), Serie.SG) is None
    # no TTL on sommari, even far in the future
    cache.put_sommario(Sommario(Serie.SG, s.data, 4, s.link, s.link_pdf, s.voci[:1]))
    assert len(cache.get_sommario(s.data, Serie.SG).voci) == 1


def test_atto_roundtrip(cache):
    assert cache.get_atto("nope") is None
    a = make_atto()
    cache.put_atto(a)
    assert cache.get_atto(a.codice) == a
    minimal = make_atto("25A00002", tipo=None, numero_gu=None, scaricato_il=None)
    cache.put_atto(minimal)
    assert cache.get_atto("25A00002") == minimal
    cache.put_atto(make_atto(testo="changed"))
    assert cache.get_atto(a.codice).testo == "changed"


def test_search_diacritics_both_ways(cache):
    cache.put_atto(make_atto(titolo="Tutela della città storica", testo="Perché sì."))
    assert [h.codice for h in hits(cache, "citta")] == ["25A00001"]
    assert [h.codice for h in hits(cache, "CITTÀ")] == ["25A00001"]
    assert hits(cache, "perche si")


def test_search_hit_fields_and_multiword_and(cache):
    cache.put_atto(make_atto())
    h = hits(cache, "trasporti pubblici")
    assert len(h) == 1
    assert h[0].serie is Serie.SG
    assert h[0].data == date(2026, 1, 5)
    assert h[0].link.endswith("25A00001")
    assert "[trasporti]" in h[0].estratto
    assert h[0].punteggio > 0
    assert hits(cache, "trasporti inesistente") == []


def test_search_ranking_prefers_better_match(cache):
    cache.put_atto(make_atto("A1", titolo="Altro", testo="energia " + "x " * 200))
    cache.put_atto(make_atto("A2", titolo="Energia rinnovabile", testo="energia energia"))
    res = hits(cache, "energia")
    assert [h.codice for h in res] == ["A2", "A1"]
    assert res[0].punteggio >= res[1].punteggio


def test_search_filters(cache):
    cache.put_atto(
        make_atto("A1", serie=Serie.SG, tipo="LEGGE", data=date(2026, 1, 1), testo="acqua")
    )
    cache.put_atto(
        make_atto("A2", serie=Serie.S4, tipo="DECRETO", data=date(2026, 2, 1), testo="acqua")
    )
    cache.put_atto(
        make_atto("A3", serie=Serie.SG, tipo="DECRETO", data=date(2026, 3, 1), testo="acqua")
    )
    codes = lambda **f: sorted(h.codice for h in hits(cache, "acqua", **f))
    assert codes() == ["A1", "A2", "A3"]
    assert codes(serie=Serie.SG) == ["A1", "A3"]
    assert codes(tipo="decreto") == ["A2", "A3"]
    assert codes(dal=date(2026, 2, 1)) == ["A2", "A3"]
    assert codes(al=date(2026, 2, 1)) == ["A1", "A2"]
    assert codes(dal=date(2026, 2, 1), al=date(2026, 2, 1)) == ["A2"]
    assert codes(serie=Serie.SG, tipo="DECRETO", dal=date(2026, 2, 15)) == ["A3"]
    assert len(hits(cache, "acqua", limite=2)) == 2
    assert hits(cache, "acqua", limite=0) == []


def test_search_covers_sommario_and_feed_titles(cache):
    cache.put_sommario(make_sommario())
    cache.put_feed(make_feed(2))
    sommario_hit = hits(cache, "mare")
    assert [h.codice for h in sommario_hit] == ["25A00010"]
    assert sommario_hit[0].data == date(2026, 1, 5)
    assert hits(cache, "giustizia")[0].codice == "25A00010"  # emettitore is indexed
    assert hits(cache, "avviso", tipo="LEGGE") == []
    assert [h.codice for h in hits(cache, "avviso", serie=Serie.SG)] == ["25A00011"]
    feed_hits = hits(cache, "agricoltura")
    assert sorted(h.codice for h in feed_hits) == ["26A00000", "26A00001"]


def test_search_one_hit_per_act_full_text_wins(cache):
    cache.put_sommario(make_sommario())
    cache.put_atto(make_atto("25A00010", titolo="Legge sul mare", testo="il mare e vasto"))
    res = hits(cache, "mare")
    assert len(res) == 1
    assert res[0].link.endswith("25A00010")  # the act's link, not the sommario voce's "l1"


def test_search_updates_after_replace(cache):
    cache.put_atto(make_atto(testo="vecchia parola"))
    cache.put_atto(make_atto(testo="nuova"))
    assert hits(cache, "vecchia") == []
    assert len(hits(cache, "nuova")) == 1


@pytest.mark.parametrize(
    "text",
    ['"', '"unclosed', "*", "foo*", "AND", "OR", "NOT x", "a AND", "NEAR(a b)", "(", "titolo:x",
     "-x", "a OR b'; DROP TABLE atti;--", "^x", "\\", "x:"],
)  # fmt: skip
def test_search_hostile_input_never_raises(cache, text):
    cache.put_atto(make_atto(testo="AND OR NOT near x titolo"))
    hits(cache, text)
    assert cache.get_atto("25A00001") is not None


def test_search_operator_words_are_literal(cache):
    cache.put_atto(make_atto("A1", testo="gatti e cani"))
    cache.put_atto(make_atto("A2", testo="solo gatti"))
    # "AND" is just a term here, so only text containing the word "and"/"AND" matches.
    assert hits(cache, "gatti AND cani") == []
    assert [h.codice for h in hits(cache, 'gatti "cani')] == ["A1"]
    assert len(hits(cache, "gat*")) == 0  # no wildcard: '*' is stripped, "gat" != "gatti"
    assert hits(cache, "   ") == [] and hits(cache, "") == [] and hits(cache, '"*"') == []


def test_build_match_query():
    assert build_match_query('a "b" AND c*') == '"a" "b" "AND" "c"'
    assert build_match_query("***") is None


def test_stats_and_clear(cache):
    cache.put_atto(make_atto())
    cache.put_feed(make_feed(2))
    cache.put_sommario(make_sommario())
    cache.put_http(RawPage("u", b"x", "t", T0))
    s = cache.stats()
    assert s["atti"] == 1 and s["feeds"] == 1 and s["feed_items"] == 2
    assert s["sommari"] == 1 and s["sommario_voci"] == 2 and s["http_pages"] == 1
    assert s["search_entries"] == 5
    cache.clear()
    assert set(cache.stats().values()) == {0}
    assert hits(cache, "decreto") == []
    cache.put_atto(make_atto())
    assert len(hits(cache, "decreto")) == 1


def test_persists_across_reopen(tmp_path, clock):
    path = tmp_path / "c.db"
    with SqliteCache(path, clock=clock) as c:
        c.put_atto(make_atto())
    with SqliteCache(path, clock=clock) as c:
        assert c.schema_version == 1
        assert c.get_atto("25A00001") is not None
        assert len(hits(c, "decreto")) == 1


def test_migration_from_empty_db(tmp_path):
    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()  # existing zero-byte database, user_version 0
    with SqliteCache(path) as c:
        assert c.schema_version == 1
        assert c.stats()["atti"] == 0


def test_migration_applies_only_missing_steps(tmp_path, monkeypatch):
    from gazzetta_mcp.cache import sqlite as mod

    path = tmp_path / "m.db"
    with SqliteCache(path) as c:
        c.put_atto(make_atto())
    monkeypatch.setattr(
        mod, "_MIGRATIONS", [*mod._MIGRATIONS, "ALTER TABLE atti ADD COLUMN extra TEXT;"]
    )
    with SqliteCache(path) as c:
        assert c.schema_version == 2
        assert c.get_atto("25A00001") is not None  # data survived the upgrade
    with SqliteCache(path) as c:  # re-opening does not re-run it
        assert c.schema_version == 2


def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    from gazzetta_mcp.cache import sqlite as mod

    path = tmp_path / "f.db"
    monkeypatch.setattr(mod, "_MIGRATIONS", [*mod._MIGRATIONS, "CREATE TABLE t(x); BOGUS;"])
    with pytest.raises(sqlite3.Error):
        SqliteCache(path)
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1  # v1 kept, v2 rolled back
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 't'").fetchone() is None
    conn.close()


def test_newer_schema_is_rejected(tmp_path):
    path = tmp_path / "n.db"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(CacheError, match="newer"):
        SqliteCache(path)


def test_missing_fts5_raises_clear_error(monkeypatch):
    real_connect = sqlite3.connect

    class NoFts(sqlite3.Connection):
        def execute(self, sql, *a):
            if "fts5" in sql.lower():
                raise sqlite3.OperationalError("no such module: fts5")
            return super().execute(sql, *a)

    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: real_connect(*a, factory=NoFts, **k))
    with pytest.raises(CacheError, match="FTS5"):
        SqliteCache(":memory:")


def test_usable_from_other_threads(cache):
    import threading

    errors: list[BaseException] = []

    def work(i: int) -> None:
        try:
            cache.put_atto(make_atto(f"T{i}", testo=f"thread{i} comune"))
            assert cache.get_atto(f"T{i}") is not None
            hits(cache, "comune")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(hits(cache, "comune")) == 8
