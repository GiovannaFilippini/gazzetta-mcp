from __future__ import annotations

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
from gazzetta_mcp.models import DISCLAIMER, Atto, Serie


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
