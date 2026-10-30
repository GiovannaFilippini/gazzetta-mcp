"""Remote archive client and service over a REAL HTTP connection on the loopback interface.

The other test files talk to the service in-process (fake ASGI / MockTransport). Here the real
service runs under uvicorn in a thread, bound to 127.0.0.1 on a port picked by the operating
system, and the real ``ClienteRemoto`` (and the ``GazzettaService`` chain on top of it) reaches
it through an actual TCP socket. Nothing leaves the machine.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from datetime import date
from typing import Any

import httpx
import pytest
import uvicorn

from gazzetta_mcp.archivio.cliente_remoto import ClienteRemoto
from gazzetta_mcp.archivio.remoto import ArchivioSolaLettura, create_app
from gazzetta_mcp.archivio.store import ArchiveStore
from gazzetta_mcp.cache.sqlite import SqliteCache
from gazzetta_mcp.config import Settings
from gazzetta_mcp.models import Atto, SearchFilters, Serie
from gazzetta_mcp.parsing import GuParser
from gazzetta_mcp.service import GazzettaService
from gazzetta_mcp.sources.gu import GuClient
from gazzetta_mcp.sources.normattiva import NormattivaLinkBuilder

from ._service_helpers import FIX, ROUTES, TODAY, NoLimit

LOOPBACK = "127.0.0.1"
SECRET = "zqxwvutsrq"  # a search word that must never show up in any log
CODICE_LUNGO = "26A05182"  # also served by the fake official sources used for the fallback
TESTO_LUNGO = "".join(f"[{i:04d} perche' l'indennita' e' di 5€] " for i in range(120))
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def atto(codice: str, serie: Serie, titolo: str, testo: str) -> Atto:
    return Atto(
        codice=codice,
        serie=serie,
        data=date(2026, 10, 3),
        titolo=titolo,
        emettitore="Ministero",
        tipo="decreto",
        testo=testo,
        link=f"https://www.gazzettaufficiale.it/atto/{codice}",
    )


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "archivio.sqlite"
    with ArchiveStore(path) as s:
        s.put_atto(atto(CODICE_LUNGO, Serie.SG, "Decreto lungo", TESTO_LUNGO), fonte="gu")
        s.put_atto(
            atto("26A00002", Serie.SG, "Concorsi infermieri", "bando infermieri"), fonte="gu"
        )
        s.put_atto(
            atto("26A00003", Serie.SG, "Solo un pezzo", "bando parziale infermieri"),
            fonte="normattiva",
            completo=False,
        )
        s.put_atto(
            atto("26E05478", Serie.S4, "Concorso riservato", "bando riservato infermieri"),
            fonte="gu",
        )
        s.put_atto(atto("26P00001", Serie.P2, "Parere riservato", "parere infermieri"), fonte="gu")
    return path


class Servizio:
    """The real remote service under uvicorn, in a thread, on a free loopback port."""

    def __init__(self, db_path, **opzioni: Any) -> None:
        self._store = ArchivioSolaLettura(db_path)
        app = create_app(self._store, **opzioni)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind((LOOPBACK, 0))  # port 0: the OS picks a free one
        self.port = self._sock.getsockname()[1]
        # Same switches as the command line entry point (see remoto.main).
        config = uvicorn.Config(
            app,
            access_log=False,
            server_header=False,
            proxy_headers=False,
            log_config=None,
            timeout_graceful_shutdown=2,
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, args=([self._sock],), name="uvicorn-test", daemon=True
        )
        self._stopped = False

    @property
    def url(self) -> str:
        return f"http://{LOOPBACK}:{self.port}/mcp"

    def start(self) -> Servizio:
        self._thread.start()
        fine = time.monotonic() + 10
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > fine:
                self.stop()
                raise RuntimeError("the test service did not start")
            time.sleep(0.01)
        return self

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._server.should_exit = True
        if self._thread.is_alive():
            self._thread.join(timeout=10)
        self._sock.close()
        self._store.close()
        assert not self._thread.is_alive(), "the test service did not stop"


@pytest.fixture
def avvia(db, monkeypatch):
    """Factory of running services; every one is stopped at teardown, even if the test failed."""
    monkeypatch.setenv("GAZZETTA_MCP_MAX_CHARS", "1000")  # force reading an act in pieces
    attivi: list[Servizio] = []

    def _avvia(**opzioni: Any) -> Servizio:
        opzioni.setdefault("limite_minuto", 600)
        opzioni.setdefault("raffica", 100)
        servizio = Servizio(db, **opzioni)
        attivi.append(servizio)
        return servizio.start()

    yield _avvia
    for servizio in reversed(attivi):
        servizio.stop()


@pytest.fixture
async def clienti():
    """Factory of real clients; closed at teardown."""
    creati: list[ClienteRemoto] = []

    def _nuovo(url: str) -> ClienteRemoto:
        c = ClienteRemoto(url, timeout=5.0)
        creati.append(c)
        return c

    yield _nuovo
    for c in creati:
        await c.aclose()


def rpc(url: str, nome: str, argomenti: dict[str, Any], **kw: Any) -> httpx.Response:
    corpo = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": nome, "arguments": argomenti},
    }
    return httpx.post(url, json=corpo, headers=HEADERS | kw.pop("headers", {}), timeout=5, **kw)


def messaggio(r: httpx.Response) -> dict[str, Any]:
    """The JSON-RPC message of a response, whether it came as plain JSON or as SSE."""
    if "text/event-stream" in r.headers["content-type"]:
        righe = [x[5:] for x in r.text.splitlines() if x.startswith("data:")]
        return json.loads(righe[0])
    return r.json()


def messaggio_errore(r: httpx.Response) -> str:
    res = messaggio(r)["result"]
    assert res["isError"] is True
    return res["content"][0]["text"]


# -- search and reading ---------------------------------------------------------------------


async def test_search_and_chunked_read_reassemble_over_tcp(avvia, clienti):
    servizio = avvia()
    c = clienti(servizio.url)
    hits = await c.cerca("infermieri", SearchFilters())
    assert {h.codice for h in hits} >= {"26A00002", "26A00003", "26E05478"}
    assert all(h.origine == "archivio_remoto" for h in hits)

    letto = await c.leggi_atto(CODICE_LUNGO)
    assert letto is not None
    assert letto.testo == TESTO_LUNGO  # several pieces, byte for byte (accents and euro sign)
    pezzi = -(-len(TESTO_LUNGO) // 1000)
    assert pezzi > 1
    assert c.contatori["ok"] == 1 + pezzi
    assert not c.sospeso


async def test_partial_act_is_refused(avvia, clienti):
    c = clienti(avvia().url)
    assert await c.leggi_atto("26A00003") is None  # archived with only part of its text
    assert c.contatori["rifiutata"] == 1
    assert not c.sospeso  # a refusal is not a failure of the service


async def test_excluded_series_is_not_revealed(avvia, clienti):
    aperto = clienti(avvia().url)
    ristretto_srv = avvia(serie_consentite=[Serie.SG])
    ristretto = clienti(ristretto_srv.url)

    # Control: the unrestricted service does serve S4 and P2.
    assert {"26E05478", "26P00001"} <= {
        h.codice for h in await aperto.cerca("infermieri", SearchFilters())
    }
    assert (await aperto.leggi_atto("26E05478")) is not None

    codici = {h.codice for h in await ristretto.cerca("infermieri", SearchFilters())}
    assert codici and not codici & {"26E05478", "26P00001"}
    assert await ristretto.cerca("infermieri", SearchFilters(serie=Serie.S4)) == []
    assert await ristretto.leggi_atto("26E05478") is None

    # On the wire an excluded act looks exactly like a missing one, and counts stay SG-only.
    escluso = messaggio_errore(
        rpc(ristretto_srv.url, "leggi_atto_archivio", {"codice": "26E05478"})
    )
    mancante = messaggio_errore(
        rpc(ristretto_srv.url, "leggi_atto_archivio", {"codice": "26X99999"})
    )
    assert escluso == mancante
    stato = messaggio(rpc(ristretto_srv.url, "stato_archivio", {}))["result"]["structuredContent"]
    assert stato["serie_consentite"] == ["SG"]
    assert stato["atti"] == 3


# -- rate limit -----------------------------------------------------------------------------


async def test_ip_limit_gives_429_retry_after_and_opens_breaker(avvia, clienti):
    servizio = avvia(limite_minuto=1, raffica=2)
    c = clienti(servizio.url)
    assert await c.cerca("infermieri", SearchFilters())
    assert await c.cerca("infermieri", SearchFilters())
    assert not c.sospeso
    assert await c.cerca("infermieri", SearchFilters()) == []  # third call: over the burst
    assert c.contatori["limitata"] == 1
    assert c.sospeso  # the breaker is open: no more traffic
    assert await c.cerca("infermieri", SearchFilters()) == []
    assert c.contatori["saltata"] == 1

    r = rpc(servizio.url, "stato_archivio", {})
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1


def _servizio_con_fonti(remoto: ClienteRemoto) -> GazzettaService:
    """The real service chain; the 'official sources' are the fixtures behind a MockTransport."""

    def handler(request: httpx.Request) -> httpx.Response:
        nome = ROUTES.get(request.url.path)
        if nome is None:
            return httpx.Response(404, text="not found")
        return httpx.Response(200, content=(FIX / nome).read_bytes())

    settings = Settings()
    cache = SqliteCache(":memory:")
    guclient = GuClient(
        settings, cache=cache, transport=httpx.MockTransport(handler), limiter=NoLimit()
    )
    return GazzettaService(
        client=guclient,
        parser=GuParser(),
        cache=cache,
        linker=NormattivaLinkBuilder(settings),
        settings=settings,
        today=lambda: TODAY,
        closers=(guclient.aclose, cache.close),
        archivio_remoto=remoto,
    )


async def test_service_chain_uses_remote_then_falls_back_when_limited(avvia, clienti):
    pezzi = -(-len(TESTO_LUNGO) // 1000)
    servizio = avvia(limite_minuto=1, raffica=1 + pezzi)  # exactly a search and a full reading
    c = clienti(servizio.url)
    svc = _servizio_con_fonti(c)
    try:
        r = await svc.cerca("infermieri", aggiorna=False)
        assert {x["codice"] for x in r["risultati"]} >= {"26A00002"}
        assert any("archivio centrale remoto" in n for n in r["note"])

        letto = await svc.leggi_atto(CODICE_LUNGO)
        assert TESTO_LUNGO[:200] in json.dumps(letto, ensure_ascii=False)

        # The burst is spent: the next call is limited, and the service must still answer
        # from the official sources.
        assert await c.cerca("infermieri", SearchFilters()) == []
        assert c.sospeso
        fallback = await svc.leggi_atto(CODICE_LUNGO, serie="SG", data="2026-10-03")
        assert fallback["testo"]
        assert TESTO_LUNGO[:200] not in json.dumps(fallback, ensure_ascii=False)
    finally:
        await svc.aclose()


# -- X-Forwarded-For ------------------------------------------------------------------------


def test_forged_forwarded_for_does_not_escape_the_limit_behind_a_proxy(avvia):
    servizio = avvia(limite_minuto=1, raffica=2, trust_proxy=True)
    # A proxy appends the real peer: the last entry is the reliable one, the first is forged.
    codici = [
        rpc(
            servizio.url,
            "stato_archivio",
            {},
            headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.9"},
        ).status_code
        for i in range(4)
    ]
    assert codici == [200, 200, 429, 429]
    # A different peer seen by the proxy has its own bucket.
    altro = rpc(servizio.url, "stato_archivio", {}, headers={"X-Forwarded-For": "x, 203.0.113.10"})
    assert altro.status_code == 200
    # And the forged prefix alone, with several header lines, still maps to the last entry.
    due_righe = httpx.Headers([("X-Forwarded-For", "1.1.1.1"), ("X-Forwarded-For", "203.0.113.9")])
    r = httpx.post(
        servizio.url,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers=httpx.Headers(list(HEADERS.items()) + list(due_righe.multi_items())),
        timeout=5,
    )
    assert r.status_code == 429


def test_forwarded_for_is_ignored_without_trust_proxy(avvia):
    servizio = avvia(limite_minuto=1, raffica=2)
    codici = [
        rpc(
            servizio.url, "stato_archivio", {}, headers={"X-Forwarded-For": f"10.0.0.{i}"}
        ).status_code
        for i in range(4)
    ]
    assert codici == [200, 200, 429, 429]


# -- body size, robots, formats -------------------------------------------------------------


def test_oversized_body_is_rejected(avvia):
    servizio = avvia()
    grande = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"x": "a" * 70_000}}
    r = httpx.post(servizio.url, json=grande, headers=HEADERS, timeout=5)
    assert r.status_code == 413
    # The service is still fine afterwards.
    assert rpc(servizio.url, "stato_archivio", {}).status_code == 200


def _a_pezzi():  # no Content-Length: the server has to count what it reads
    for _ in range(10):
        yield b"a" * 8192


def test_oversized_chunked_body_is_not_served(avvia):
    servizio = avvia()
    r = httpx.post(servizio.url, content=_a_pezzi(), headers=HEADERS, timeout=5)
    assert r.status_code >= 400  # rejected, whatever the exact status
    assert rpc(servizio.url, "stato_archivio", {}).status_code == 200


@pytest.mark.xfail(
    reason="Real bug: an oversized chunked body (no Content-Length) gets 500 over a real "
    "connection, not 413. LimiteRichieste fakes http.disconnect to the app, the MCP layer "
    "answers 500 itself (and logs a traceback), so the 'not sent yet' 413 branch never runs.",
    strict=False,
)
def test_oversized_chunked_body_gets_413(avvia):
    servizio = avvia()
    r = httpx.post(servizio.url, content=_a_pezzi(), headers=HEADERS, timeout=5)
    assert r.status_code == 413


def test_robots_txt_disallows_everything(avvia):
    servizio = avvia()
    r = httpx.get(f"http://{LOOPBACK}:{servizio.port}/robots.txt", timeout=5)
    assert r.status_code == 200
    assert r.text == "User-agent: *\nDisallow: /\n"
    assert "server" not in r.headers  # --no server header, like the command line entry point


def test_response_is_json_or_sse_and_both_are_understood(avvia):
    from gazzetta_mcp.archivio.cliente_remoto import _estrai

    servizio = avvia()
    r = rpc(servizio.url, "stato_archivio", {})
    tipo = r.headers["content-type"]
    assert "application/json" in tipo or "text/event-stream" in tipo
    strutturato = _estrai(r.content, tipo)
    assert isinstance(strutturato, dict)
    assert strutturato["atti"] == 5


# -- failure of the service ------------------------------------------------------------------


async def test_service_stopped_midway_makes_the_client_fall_back(avvia, clienti):
    servizio = avvia()
    c = clienti(servizio.url)
    svc = _servizio_con_fonti(c)
    try:
        assert await c.cerca("infermieri", SearchFilters())  # the connection is now pooled
        servizio.stop()
        # Each call below is a refused connection (about 2 s each on Windows, instant on Linux).
        r = await svc.cerca("infermieri", aggiorna=False)
        assert r["totale"] == 0
        letto = await svc.leggi_atto(CODICE_LUNGO, serie="SG", data="2026-10-03")
        assert letto["testo"]  # served by the official sources
        assert c.contatori["rete"] == 2  # both calls failed quietly, nothing was raised
    finally:
        await svc.aclose()


# -- privacy --------------------------------------------------------------------------------


async def test_search_text_never_reaches_the_logs(avvia, clienti, caplog):
    caplog.set_level(logging.DEBUG)
    servizio = avvia(limite_minuto=1, raffica=3)
    c = clienti(servizio.url)
    svc = _servizio_con_fonti(c)
    try:
        await c.cerca(SECRET, SearchFilters())
        await svc.cerca(f"{SECRET} infermieri", aggiorna=False)
        rpc(servizio.url, "cerca_archivio", {"testo": SECRET * 40})  # too long: tool error
        await c.cerca(SECRET, SearchFilters())  # 429: breaker opens, logs a notice
        servizio.stop()
        await c.cerca(SECRET, SearchFilters())
    finally:
        await svc.aclose()
    assert caplog.records  # something was captured, so the check below is meaningful
    assert SECRET not in caplog.text
