from __future__ import annotations

import dataclasses
import sqlite3
from datetime import date

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from gazzetta_mcp.archivio import remoto
from gazzetta_mcp.archivio.remoto import (
    ArchivioSolaLettura,
    LimiteRichieste,
    TokenBucket,
    create_app,
    create_server,
    ip_cliente,
)
from gazzetta_mcp.archivio.store import ArchiveError, ArchiveStore
from gazzetta_mcp.archivio.tipi import Arco
from gazzetta_mcp.models import DISCLAIMER, Atto, SearchFilters, Serie


def make_atto(codice: str, titolo: str, testo: str, giorno: date = date(2026, 10, 3)) -> Atto:
    return Atto(
        codice=codice,
        serie=Serie.SG,
        data=giorno,
        titolo=titolo,
        emettitore="Ministero",
        tipo="decreto",
        testo=testo,
        link=f"https://example.test/{codice}",
    )


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "archivio.sqlite"
    with ArchiveStore(path) as s:
        s.put_atto(
            make_atto("26A00001", "Bonus edilizio", "Il bonus edilizio spetta " * 50), fonte="gu"
        )
        s.put_atto(
            make_atto("26A00002", "Legge sui concorsi", "concorsi per infermieri"),
            fonte="normattiva",
        )
        s.put_atto(
            make_atto("26A00003", "Solo primo articolo", "Art. 1 concorsi"),
            fonte="normattiva",
            completo=False,
        )
        s.put_archi([Arco("26A00002", "26A00001", "modifica", "normattiva")])
    return path


@pytest.fixture
def store(db):
    s = ArchivioSolaLettura(db)
    yield s
    s.close()


@pytest.fixture
async def client(store):
    async with Client(create_server(store)) as c:
        yield c


def data_of(result):
    return result.data if hasattr(result, "data") and result.data else result.structured_content


# -- read-only ----------------------------------------------------------------------------


def test_connection_cannot_write(store):
    with pytest.raises(sqlite3.OperationalError):
        store._conn.execute("DELETE FROM atti")
    with pytest.raises(sqlite3.OperationalError):
        store.set_stato("x", "y")


def test_missing_or_foreign_file_is_an_archive_error(tmp_path):
    with pytest.raises(ArchiveError):
        ArchivioSolaLettura(tmp_path / "manca.sqlite")
    other = tmp_path / "altro.sqlite"
    sqlite3.connect(other).close()
    with pytest.raises(ArchiveError):
        ArchivioSolaLettura(other)


# -- tools --------------------------------------------------------------------------------


async def test_lists_the_four_tools(client):
    names = {t.name for t in await client.list_tools()}
    assert names == {"cerca_archivio", "leggi_atto_archivio", "storico_atto", "stato_archivio"}


async def test_search_has_disclaimer_and_attribution(client):
    r = data_of(await client.call_tool("cerca_archivio", {"testo": "infermieri"}))
    assert r["numero_risultati"] == 1
    assert r["risultati"][0]["fonte"] == "normattiva"
    assert r["avviso"] == DISCLAIMER
    assert "CC BY 4.0" in r["attribuzione"]


async def test_search_gu_only_has_no_attribution(client):
    r = data_of(await client.call_tool("cerca_archivio", {"testo": "bonus"}))
    assert r["numero_risultati"] == 1
    assert "attribuzione" not in r
    assert r["avviso"] == DISCLAIMER


async def test_search_filters_and_limit_cap(client):
    r = data_of(
        await client.call_tool("cerca_archivio", {"testo": "concorsi", "dal": "2027-01-01"})
    )
    assert r["numero_risultati"] == 0
    r = data_of(await client.call_tool("cerca_archivio", {"testo": "concorsi", "limite": 100000}))
    assert r["numero_risultati"] == 2


@pytest.mark.parametrize(
    "args",
    [
        {"testo": "x" * 201},
        {"testo": "   "},
        {"testo": "a", "dal": "ieri"},
        {"testo": "a", "serie": "ZZ"},
        {"testo": "a", "tipo": "t" * 500},
    ],
)
async def test_search_bad_input_is_an_italian_error(client, args):
    with pytest.raises(ToolError) as exc:
        await client.call_tool("cerca_archivio", args)
    assert "Traceback" not in str(exc.value)


async def test_search_syntax_garbage_does_not_crash(client):
    r = data_of(await client.call_tool("cerca_archivio", {"testo": 'AND OR NEAR(" * ('}))
    assert "risultati" in r


async def test_read_in_chunks(client, monkeypatch, store):
    monkeypatch.setenv("GAZZETTA_MCP_MAX_CHARS", "1000")
    async with Client(create_server(store)) as c:
        first = data_of(await c.call_tool("leggi_atto_archivio", {"codice": "26A00001"}))
        assert len(first["testo"]) == 1000
        assert first["prossimo_offset"] == 1000
        assert first["avviso"] == DISCLAIMER
        text = first["testo"]
        offset = first["prossimo_offset"]
        while offset is not None:
            nxt = data_of(
                await c.call_tool("leggi_atto_archivio", {"codice": "26A00001", "offset": offset})
            )
            text += nxt["testo"]
            offset = nxt["prossimo_offset"]
        assert text == "Il bonus edilizio spetta " * 50


async def test_read_normattiva_has_attribution(client):
    r = data_of(await client.call_tool("leggi_atto_archivio", {"codice": "26A00002"}))
    assert "CC BY 4.0" in r["attribuzione"]
    assert r["prossimo_offset"] is None


async def test_read_partial_text_is_refused(client):
    with pytest.raises(ToolError) as exc:
        await client.call_tool("leggi_atto_archivio", {"codice": "26A00003"})
    assert "link ufficiale" in str(exc.value)


async def test_read_unknown_code(client):
    with pytest.raises(ToolError) as exc:
        await client.call_tool("leggi_atto_archivio", {"codice": "NOPE"})
    assert "non presente" in str(exc.value)


async def test_history(client):
    r = data_of(await client.call_tool("storico_atto", {"codice": "26A00001", "profondita": 99}))
    assert [(v["codice"], v["direzione"]) for v in r["voci"]] == [("26A00002", "agisce_su")]
    assert r["voci"][0]["archiviato"] is True
    assert r["avviso"] == DISCLAIMER
    assert "CC BY 4.0" in r["attribuzione"]


async def test_status(client):
    r = data_of(await client.call_tool("stato_archivio", {}))
    assert r["atti"] == 3
    assert r["atti_per_fonte"] == {"gu": 1, "normattiva": 2}
    assert r["ultimo_aggiornamento"]
    assert "CC BY 4.0" in r["attribuzioni"][0]
    assert r["avviso"] == DISCLAIMER


async def test_unexpected_error_is_masked(client, store, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("segreto interno /percorso/file")

    monkeypatch.setattr(store, "search", boom)
    with pytest.raises(ToolError) as exc:
        await client.call_tool("cerca_archivio", {"testo": "bonus"})
    assert "segreto" not in str(exc.value)
    assert "riprova" in str(exc.value)


# -- rate limit ---------------------------------------------------------------------------


def test_token_bucket_burst_and_refill():
    now = [0.0]
    b = TokenBucket(60, 3, clock=lambda: now[0])  # 1 token per second
    assert [b.allow("a")[0] for _ in range(4)] == [True, True, True, False]
    assert b.allow("b")[0] is True  # another IP is independent
    ok, wait = b.allow("a")
    assert not ok and 0 < wait <= 1.0
    now[0] += 1.0
    assert b.allow("a")[0] is True
    now[0] += 1000
    assert [b.allow("a")[0] for _ in range(4)] == [True, True, True, False]  # capped at burst


def test_token_bucket_memory_is_bounded():
    b = TokenBucket(60, 1, max_keys=10)
    for i in range(100):
        b.allow(f"ip{i}")
    assert len(b._buckets) == 10


def test_ip_comes_from_socket_unless_proxy_is_trusted():
    scope = {"client": ("1.2.3.4", 5), "headers": [(b"x-forwarded-for", b"9.9.9.9, 8.8.8.8")]}
    assert ip_cliente(scope, trust_proxy=False) == "1.2.3.4"
    assert ip_cliente(scope, trust_proxy=True) == "8.8.8.8"  # last entry: set by our proxy
    assert ip_cliente({"client": ("1.2.3.4", 5), "headers": []}, trust_proxy=True) == "1.2.3.4"


def _http(app, **kw):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, **kw), base_url="http://t")


async def test_middleware_returns_429_in_italian_per_ip(store):
    now = [0.0]
    app = create_app(store, limite_minuto=60, raffica=2, clock=lambda: now[0])
    async with _http(app, client=("1.1.1.1", 1)) as c:
        codes = [(await c.get("/robots.txt")).status_code for _ in range(3)]
        assert codes == [200, 200, 429]
        r = await c.get("/robots.txt")
        assert "Troppe richieste" in r.text and int(r.headers["retry-after"]) >= 1
    async with _http(app, client=("2.2.2.2", 1)) as c:
        assert (await c.get("/robots.txt")).status_code == 200


async def test_forwarded_header_ignored_without_trust_proxy(store):
    app = create_app(store, limite_minuto=60, raffica=1, clock=lambda: 0.0)
    async with _http(app, client=("1.1.1.1", 1)) as c:
        assert (
            await c.get("/robots.txt", headers={"x-forwarded-for": "5.5.5.5"})
        ).status_code == 200
        # spoofing another address does not give a new bucket
        assert (
            await c.get("/robots.txt", headers={"x-forwarded-for": "6.6.6.6"})
        ).status_code == 429


async def test_forwarded_header_used_with_trust_proxy(store):
    app = create_app(store, limite_minuto=60, raffica=1, trust_proxy=True, clock=lambda: 0.0)
    async with _http(app, client=("1.1.1.1", 1)) as c:
        h5 = {"x-forwarded-for": "5.5.5.5"}
        assert (await c.get("/robots.txt", headers=h5)).status_code == 200
        assert (await c.get("/robots.txt", headers=h5)).status_code == 429
        assert (
            await c.get("/robots.txt", headers={"x-forwarded-for": "6.6.6.6"})
        ).status_code == 200


async def test_oversized_body_is_refused(store):
    app = create_app(store)
    async with _http(app) as c:
        r = await c.post("/mcp", content=b"x" * (remoto.MAX_BODY + 1))
        assert r.status_code == 413


async def test_robots_disallows_everything(store):
    async with _http(create_app(store)) as c:
        r = await c.get("/robots.txt")
    assert "Disallow: /" in r.text


async def test_non_http_scopes_pass_through():
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    mw = LimiteRichieste(inner, bucket=TokenBucket(1, 1))
    await mw({"type": "lifespan"}, None, None)
    assert seen == ["lifespan"]


def test_cli_rejects_missing_archive(tmp_path, capsys):
    assert remoto.main(["--archivio", str(tmp_path / "no.sqlite")]) == 1
    assert "Errore" in capsys.readouterr().out


def test_several_forwarded_for_lines_use_the_last_entry_of_the_last_line():
    from gazzetta_mcp.archivio.remoto import ip_cliente

    scope = {
        "headers": [(b"x-forwarded-for", b"6.6.6.6, 7.7.7.7"), (b"x-forwarded-for", b"10.0.0.77")],
        "client": ("1.2.3.4", 1),
    }
    assert ip_cliente(scope, trust_proxy=True) == "10.0.0.77"
    assert ip_cliente(scope, trust_proxy=False) == "1.2.3.4"


def test_read_only_store_stays_read_only_after_a_read(tmp_path):
    import sqlite3

    import pytest

    from gazzetta_mcp.archivio import ArchiveStore
    from gazzetta_mcp.archivio.remoto import ArchivioSolaLettura

    path = tmp_path / "a.sqlite3"
    ArchiveStore(path).close()
    ro = ArchivioSolaLettura(path)
    ro.read("SELECT 1")
    assert ro._conn.execute("PRAGMA query_only").fetchone()[0] == 1
    with pytest.raises(sqlite3.Error):
        ro._conn.execute("CREATE TABLE x (a)")


def test_an_archive_with_an_old_schema_is_refused_with_a_clear_message(tmp_path):
    import sqlite3

    import pytest

    from gazzetta_mcp.archivio import ArchiveError
    from gazzetta_mcp.archivio.remoto import ArchivioSolaLettura

    path = tmp_path / "vecchio.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE atti (codice TEXT)")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()
    with pytest.raises(ArchiveError, match="schema v1"):
        ArchivioSolaLettura(path)


# -- series scope (--serie) ---------------------------------------------------------------


def make_atto_serie(codice: str, serie: Serie, titolo: str, testo: str) -> Atto:
    return dataclasses.replace(make_atto(codice, titolo, testo), serie=serie)


@pytest.fixture
def db_misto(tmp_path):
    """SG and S1 acts next to excluded ones (S4 contest, P2 notice) sharing the same words."""
    path = tmp_path / "misto.sqlite"
    with ArchiveStore(path) as s:
        s.put_atto(make_atto("26A00001", "Bonus edilizio", "bonus segreto " * 5), fonte="gu")
        s.put_atto(make_atto("26A00002", "Altra legge", "concorsi generali"), fonte="gu")
        s.put_atto(
            make_atto_serie("26E10001", Serie.S4, "Concorso riservato", "concorsi segreto"),
            fonte="gu",
        )
        s.put_atto(
            make_atto_serie("26E10002", Serie.P2, "Avviso riservato", "concorsi segreto"),
            fonte="gu",
        )
        s.put_atto(
            make_atto_serie("26C00001", Serie.S1, "Sentenza", "concorsi sentenza"), fonte="gu"
        )
        s.put_atto(make_atto("26A00003", "Terza legge", "testo"), fonte="gu")
        # 26A00002 modifies 26A00001 directly; the excluded 26E10001 modifies 26A00001 too and
        # is itself modified by the visible 26A00003 (reachable only through the hidden act).
        s.put_archi(
            [
                Arco("26A00002", "26A00001", "modifica", "gu"),
                Arco("26E10001", "26A00001", "modifica", "gu"),
                Arco("26A00003", "26E10001", "modifica", "gu"),
                Arco("26A00001", "26E10002", "modifica", "gu"),
            ]
        )
        s.aggiungi_numeri([(Serie.SG, date(2026, 10, 3), 230), (Serie.S4, date(2026, 10, 3), 80)])
    return path


@pytest.fixture
def store_misto(db_misto):
    s = ArchivioSolaLettura(db_misto)
    yield s
    s.close()


@pytest.fixture
async def client_sg(store_misto):
    async with Client(create_server(store_misto, [Serie.SG])) as c:
        yield c


@pytest.fixture
async def client_sg_s1(store_misto):
    async with Client(create_server(store_misto, [Serie.SG, Serie.S1])) as c:
        yield c


def assert_no_leak(payload) -> None:
    text = str(payload)
    for hidden in ("26E10001", "26E10002", "S4", "P2", "Concorso riservato", "Avviso riservato"):
        assert hidden not in text


async def test_scope_search_only_returns_allowed_series(client_sg):
    r = data_of(await client_sg.call_tool("cerca_archivio", {"testo": "concorsi segreto"}))
    assert {x["serie"] for x in r["risultati"]} <= {"SG"}
    assert_no_leak(r)
    r = data_of(await client_sg.call_tool("cerca_archivio", {"testo": "segreto"}))
    assert [x["codice"] for x in r["risultati"]] == ["26A00001"]
    assert_no_leak(r)


async def test_scope_search_explicit_excluded_series_is_refused(client_sg):
    for serie in ("S4", "p2", "S1"):
        with pytest.raises(ToolError) as exc:
            await client_sg.call_tool("cerca_archivio", {"testo": "concorsi", "serie": serie})
        assert "solo nelle serie: SG" in str(exc.value)
        assert serie.upper() not in str(exc.value).replace("SG", "")
    r = data_of(await client_sg.call_tool("cerca_archivio", {"testo": "concorsi", "serie": "sg"}))
    assert r["numero_risultati"] == 1


async def test_scope_search_multiple_series_merges_and_respects_limit(client_sg_s1):
    r = data_of(await client_sg_s1.call_tool("cerca_archivio", {"testo": "concorsi"}))
    assert {x["codice"] for x in r["risultati"]} == {"26A00002", "26C00001"}
    assert_no_leak(r)
    uno = data_of(
        await client_sg_s1.call_tool("cerca_archivio", {"testo": "concorsi", "limite": 1})
    )
    assert uno["numero_risultati"] == 1
    # The merged top hit is the best of the union, whatever the series it comes from.
    assert uno["risultati"][0]["codice"] == r["risultati"][0]["codice"]


def test_scope_merge_matches_single_search_over_the_union(store_misto):
    unione = store_misto.cerca_in_serie("concorsi", SearchFilters(limite=2), [Serie.SG, Serie.S1])
    tutti = store_misto.search("concorsi", SearchFilters(limite=50))
    attesi = [h.codice for h in tutti if h.serie in (Serie.SG, Serie.S1)][:2]
    assert [h.codice for h in unione] == attesi


async def test_scope_read_excluded_act_looks_missing(client_sg):
    with pytest.raises(ToolError) as missing:
        await client_sg.call_tool("leggi_atto_archivio", {"codice": "NOPE"})
    for codice in ("26E10001", "26E10002", "26C00001"):
        with pytest.raises(ToolError) as hidden:
            await client_sg.call_tool("leggi_atto_archivio", {"codice": codice})
        assert str(hidden.value) == str(missing.value)
    r = data_of(await client_sg.call_tool("leggi_atto_archivio", {"codice": "26A00001"}))
    assert r["serie"] == "SG"


async def test_scope_history_hides_excluded_nodes_and_what_hangs_from_them(client_sg):
    r = data_of(await client_sg.call_tool("storico_atto", {"codice": "26A00001"}))
    assert [(v["codice"], v["profondita"]) for v in r["voci"]] == [("26A00002", 1)]
    assert_no_leak(r)


async def test_scope_history_of_excluded_start_is_empty(client_sg):
    r = data_of(await client_sg.call_tool("storico_atto", {"codice": "26E10001"}))
    unknown = data_of(await client_sg.call_tool("storico_atto", {"codice": "NOPE"}))
    assert r["voci"] == [] and r["numero_voci"] == 0
    assert r["voci"] == unknown["voci"] and r["troncato"] == unknown["troncato"]


async def test_scope_history_unrestricted_server_is_unchanged(store_misto):
    async with Client(create_server(store_misto)) as c:
        r = data_of(await c.call_tool("storico_atto", {"codice": "26A00001"}))
    assert {"26E10001", "26A00003"} <= {v["codice"] for v in r["voci"]}


async def test_scope_status_counts_only_allowed_series(client_sg, client_sg_s1):
    r = data_of(await client_sg.call_tool("stato_archivio", {}))
    assert r["serie_consentite"] == ["SG"]
    assert r["atti"] == 3
    assert r["atti_per_fonte"] == {"gu": 3}
    assert sum(r["numeri"].values()) == 1
    assert_no_leak(r)
    r = data_of(await client_sg_s1.call_tool("stato_archivio", {}))
    assert r["serie_consentite"] == ["SG", "S1"]
    assert r["atti"] == 4


def test_parse_serie():
    assert remoto.parse_serie("SG") == [Serie.SG]
    assert remoto.parse_serie(" sg , S1,SG") == [Serie.SG, Serie.S1]
    for bad in ("", " , ", "SG,XX"):
        with pytest.raises(ValueError):
            remoto.parse_serie(bad)


def test_cli_rejects_invalid_serie(db_misto, capsys):
    assert remoto.main(["--archivio", str(db_misto), "--serie", "ZZ"]) == 2
    assert "--serie" in capsys.readouterr().out
