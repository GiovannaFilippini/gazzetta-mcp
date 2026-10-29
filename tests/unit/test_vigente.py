from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from gazzetta_mcp.cache.sqlite import SqliteCache
from gazzetta_mcp.config import Settings
from gazzetta_mcp.models import DISCLAIMER
from gazzetta_mcp.parsing._util import ParseError
from gazzetta_mcp.parsing.vigente import NoActError, html_to_text, parse_articolo
from gazzetta_mcp.service import Limits
from gazzetta_mcp.sources.gu import GuHttpError
from gazzetta_mcp.sources.normattiva_vigente import (
    NormattivaVigenteClient,
    VigenteNotFoundError,
)
from gazzetta_mcp.tools.vigente import register_vigente
from gazzetta_mcp.vigente import ATTRIBUZIONE, split_articolo

from ._service_helpers import NoLimit, make_service

FIX = Path(__file__).parent.parent / "fixtures" / "vigente"
PRIMO = (FIX / "dettaglio_legge_1990_241_primo_articolo.json").read_bytes()
ART2 = (FIX / "dettaglio_legge_1990_241_art2.json").read_bytes()
ART3BIS = (FIX / "dettaglio_legge_1990_241_art3bis.json").read_bytes()
NON_TROVATO = (FIX / "errore_articolo_inesistente.json").read_bytes()
URN_BASE = "urn:nir:stato:legge:1990;241"

ANSWERS = {
    URN_BASE: PRIMO,
    URN_BASE + "~art2": ART2,
    URN_BASE + "~art3bis": ART3BIS,
    "urn:nir:stato:legge:1990-08-07;241~art2": ART2,
}


def mock(seen: list[httpx.Request] | None = None, status: int | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if status is not None:
            return httpx.Response(status, content=b"boom")
        urn = json.loads(request.content)["urn"]
        if urn in ANSWERS:
            return httpx.Response(200, content=ANSWERS[urn])
        return httpx.Response(404, content=NON_TROVATO)

    return httpx.MockTransport(handler)


def make_mcp(transport, max_chars: int | None = None, cache: SqliteCache | None = None):
    service, *_ = make_service(
        limits=Limits(max_chars=max_chars) if max_chars else None, cache=cache
    )
    mcp = FastMCP("test")
    register_vigente(mcp, lambda: service, transport=transport)
    return mcp


async def call(mcp: FastMCP, **args):
    async with Client(mcp) as c:
        return (await c.call_tool("testo_vigente", args)).data


# --- parsing -------------------------------------------------------------------------


def test_parse_primo_articolo_has_preamble_heading_and_amendment_marks():
    art = parse_articolo(PRIMO)
    assert art.titolo == "LEGGE 7 agosto 1990, n. 241"
    assert art.sottotitolo.startswith("Nuove norme in materia di procedimento amministrativo")
    assert "IL PRESIDENTE DELLA REPUBBLICA" in art.testo
    assert "Art. 1\n(Principi generali dell'attività amministrativa)" in art.testo
    assert "1-bis. La pubblica amministrazione" in art.testo
    assert "((2-bis. I rapporti tra il cittadino" in art.testo
    assert art.in_vigore_dal == date(2020, 9, 15)
    assert art.fino_al is None and art.altre_versioni == 0
    assert "<" not in art.testo and "&egrave;" not in art.testo


def test_parse_art2_keeps_updates_and_reads_vigenza():
    art = parse_articolo(ART2)
    assert art.in_vigore_dal == date(2021, 6, 1)
    assert "Art. 2\n(Conclusione del procedimento)" in art.testo
    assert "trenta giorni. (14)" in art.testo


def test_parse_art3bis_is_short_and_dated():
    art = parse_articolo(ART3BIS)
    assert "Art. 3-bis" in art.testo
    assert art.in_vigore_dal == date(2020, 7, 17)


def test_html_to_text_one_line_per_block_and_br():
    html = "<div><h2>Art. 9</h2><div><span>1. </span>uno<br>due</div><div>2. tre</div></div>"
    assert html_to_text(html) == "Art. 9\n1. uno\ndue\n2. tre"


def test_parse_errors():
    with pytest.raises(ParseError):
        parse_articolo(b"<html>no json</html>")
    with pytest.raises(NoActError):
        parse_articolo(b'{"message":"Atto non trovato","code":null}')
    with pytest.raises(NoActError):
        parse_articolo(b'{"data":{"atto":null,"lista":null}}')
    with pytest.raises(ParseError):
        parse_articolo(b'{"data":{"atto":{"articoloHtml":"  "}}}')


def test_parse_ambiguous_takes_the_first_and_counts_the_others():
    atto = json.loads(PRIMO)["data"]["atto"]
    answer = json.dumps({"data": {"atto": None, "lista": [atto, dict(atto, titolo="BIS")]}})
    art = parse_articolo(answer.encode())
    assert art.titolo == "LEGGE 7 agosto 1990, n. 241" and art.altre_versioni == 1


# --- reading the article from the words of the user ----------------------------------


@pytest.mark.parametrize(
    ("text", "words", "articolo"),
    [
        ("legge 241/1990", "legge 241/1990", None),
        ("legge 241 del 1990", "legge 241/1990", None),
        ("legge 241/1990 art. 3", "legge 241/1990", "3"),
        ("articolo 3-bis della legge 241/1990", "legge 241/1990", "3bis"),
        ("art 5 bis del decreto legislativo 33/2013", "decreto legislativo 33/2013", "5bis"),
        ("DPR 26 ottobre 1972 n. 633, art. 17 ter", "DPR 26 ottobre 1972 n. 633", "17ter"),
        ("legge 7 agosto 1990, n. 241", "legge 7 agosto 1990, n. 241", None),
        ("dl 144/2026 ARTICOLO 12", "dl 144/2026", "12"),
    ],
)
def test_split_articolo(text, words, articolo):
    assert split_articolo(text) == (words, articolo)


async def test_tool_reads_the_first_article_with_attribution_and_links():
    seen: list[httpx.Request] = []
    data = await call(make_mcp(mock(seen)), atto="legge 241 del 1990")
    assert len(seen) == 1
    assert json.loads(seen[0].content) == {"urn": URN_BASE}
    assert seen[0].headers["user-agent"].startswith("gazzetta-mcp/")
    assert data["avvertenza"] == DISCLAIMER
    assert (
        data["attribuzione"]
        == ATTRIBUZIONE
        == ("Normattiva Open Data (dati.normattiva.it), licenza CC BY 4.0")
    )
    assert "fa fede solo il testo pubblicato nella Gazzetta Ufficiale" in data["nota"]
    assert "CC BY 4.0" in data["nota"]
    assert data["licenza"] == "https://creativecommons.org/licenses/by/4.0/"
    assert "convertito" in data["modifiche"]
    assert "solo il primo articolo" in data["nota"] or "primo articolo" in data["nota"]
    assert data["link_normattiva"] == "https://www.normattiva.it/uri-res/N2Ls?" + URN_BASE
    assert data["fonte"] and all(u.startswith("http") for u in data["fonte"])
    assert data["in_vigore_dal"] == "2020-09-15"
    assert data["articolo"] == "1 (primo articolo)"
    assert data["titolo"] == "LEGGE 7 agosto 1990, n. 241"
    assert not data["troncato"] and data["prossimo_offset"] is None
    assert data["caratteri_totali"] == len(data["testo"])


async def test_tool_reads_a_named_article_and_a_bis_article():
    seen: list[httpx.Request] = []
    mcp = make_mcp(mock(seen))
    data = await call(mcp, atto="legge 241/1990 art. 2")
    assert data["articolo"] == "2"
    assert "Conclusione del procedimento" in data["testo"]
    assert data["link_normattiva"].endswith(URN_BASE + "~art2")
    assert "primo articolo" not in data["nota"]
    data = await call(mcp, atto="articolo 3-bis della legge 241/1990")
    assert data["articolo"] == "3-bis" and data["in_vigore_dal"] == "2020-07-17"
    assert json.loads(seen[-1].content)["urn"] == URN_BASE + "~art3bis"


async def test_full_date_is_used_in_the_reference():
    seen: list[httpx.Request] = []
    data = await call(make_mcp(mock(seen)), atto="legge 7 agosto 1990, n. 241 art. 2")
    assert json.loads(seen[0].content)["urn"] == "urn:nir:stato:legge:1990-08-07;241~art2"
    assert data["atto"] == "Legge 7 agosto 1990, n. 241"


async def test_long_text_is_paged_with_offset():
    mcp = make_mcp(mock(), max_chars=1000)
    first = await call(mcp, atto="legge 241/1990 art. 2")
    total = first["caratteri_totali"]
    assert first["troncato"] and first["prossimo_offset"] == 1000 and total > 1000
    assert "offset=1000" in first["testo"]
    parts, offset = [], 0
    while offset is not None:
        page = await call(mcp, atto="legge 241/1990 art. 2", offset=offset)
        assert page["offset"] == offset
        parts.append(page["testo"].split("\n\n[... testo troncato")[0])
        offset = page["prossimo_offset"]
    assert "".join(parts) == parse_articolo(ART2).testo


async def test_second_call_is_served_from_the_cache(tmp_path):
    seen: list[httpx.Request] = []
    cache = SqliteCache(tmp_path / "c.sqlite3")
    mcp = make_mcp(mock(seen), cache=cache)
    await call(mcp, atto="legge 241/1990 art. 2")
    again = await call(mcp, atto="legge 241 del 1990 articolo 2")
    assert len(seen) == 1 and again["articolo"] == "2"
    cache.close()


# --- errors: short, Italian, with advice ----------------------------------------------


async def test_unknown_article_gives_advice():
    with pytest.raises(ToolError, match=r"articolo 99 .*3-bis"):
        await call(make_mcp(mock()), atto="legge 241/1990 art. 99")


async def test_unknown_act_gives_advice():
    with pytest.raises(ToolError, match="Non ho trovato 'Legge n. 999 del 1990' su Normattiva"):
        await call(make_mcp(mock()), atto="legge 999/1990")


async def test_unreadable_reference_reuses_the_link_help():
    with pytest.raises(ToolError, match="Non riesco a interpretare"):
        await call(make_mcp(mock()), atto="una legge sulla caccia")


async def test_editorial_code_alone_is_not_enough():
    with pytest.raises(ToolError, match="tipo, numero e anno"):
        await call(make_mcp(mock()), atto="26A05182")


async def test_negative_offset_and_offset_too_big():
    mcp = make_mcp(mock())
    with pytest.raises(ToolError, match="negativo"):
        await call(mcp, atto="legge 241/1990", offset=-1)
    with pytest.raises(ToolError, match="supera la lunghezza"):
        await call(mcp, atto="legge 241/1990", offset=10**6)


async def test_server_error_and_bad_answer_are_friendly():
    with pytest.raises(ToolError, match="Normattiva non risponde"):
        await call(make_mcp(mock(status=503)), atto="legge 241/1990")

    def junk(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>manutenzione</html>")

    with pytest.raises(ToolError, match="Non sono riuscito a leggere la risposta di Normattiva"):
        await call(make_mcp(httpx.MockTransport(junk)), atto="legge 241/1990")


# --- client --------------------------------------------------------------------------


async def test_client_maps_statuses():
    for status, exc in (
        (404, VigenteNotFoundError),
        (400, VigenteNotFoundError),
        (500, GuHttpError),
    ):
        client = NormattivaVigenteClient(
            Settings(), transport=mock(status=status), limiter=NoLimit()
        )
        with pytest.raises(exc):
            await client.get_articolo(URN_BASE)
        await client.aclose()


async def test_client_network_error_is_a_gu_error():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = NormattivaVigenteClient(
        Settings(), transport=httpx.MockTransport(boom), limiter=NoLimit()
    )
    with pytest.raises(GuHttpError):
        await client.get_articolo(URN_BASE)
    await client.aclose()
