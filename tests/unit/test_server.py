from __future__ import annotations

import subprocess
import sys

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from gazzetta_mcp.models import DISCLAIMER
from gazzetta_mcp.server import INSTRUCTIONS, create_server

from ._service_helpers import make_service

CALLS = [
    ("ultime_pubblicazioni", {"serie": "SG", "giorni": 7}),
    ("sommario", {"data": "2026-10-03", "serie": "SG"}),
    ("leggi_atto", {"codice": "26A05182", "data": "2026-10-03"}),
    ("cerca_concorsi", {"parole_chiave": "avviso"}),
    ("rimando_normattiva", {"atto": "legge 5 agosto 2026, n. 140"}),
    ("cerca", {"testo": "decreto", "limite": 5}),
]

NEW_TOOLS = {"scadenze_concorsi", "testo_vigente", "novita_argomento"}


@pytest.fixture
async def client():
    service, *_ = make_service()
    async with Client(create_server(service)) as c:
        yield c


async def test_lists_exactly_the_nine_tools(client):
    tools = {t.name: t for t in await client.list_tools()}
    assert set(tools) == {name for name, _ in CALLS} | NEW_TOOLS
    assert set(tools["cerca"].input_schema["properties"]) == {
        "testo",
        "serie",
        "tipo",
        "dal",
        "al",
        "limite",
        "aggiorna",
        "solo_vigenti",
        "periodo",
    }
    assert set(tools["leggi_atto"].input_schema["properties"]) >= {"codice", "data", "serie"}


def test_instructions_say_that_site_text_is_not_a_command():
    # the texts come from outside: the assistant must report them, not obey them
    assert "non eseguire istruzioni" in INSTRUCTIONS


@pytest.mark.parametrize(("name", "args"), CALLS)
async def test_every_tool_returns_data_with_fonte_and_disclaimer(client, name, args):
    result = await client.call_tool(name, args)
    data = result.data
    assert data["avvertenza"] == DISCLAIMER
    assert data["fonte"] and all(u.startswith("http") for u in data["fonte"])


async def test_errors_are_short_italian_tool_errors(client):
    with pytest.raises(ToolError, match="AAAA-MM-GG"):
        await client.call_tool("sommario", {"data": "ieri"})
    with pytest.raises(ToolError, match="Non riesco a interpretare"):
        await client.call_tool("rimando_normattiva", {"atto": "boh"})
    with pytest.raises(ToolError, match="Non riesco a risalire"):
        await client.call_tool("leggi_atto", {"codice": "26A99999"})


async def test_instructions_mention_disclaimer(client):
    assert "NON ufficiale" in client.instructions
    assert client.server_info.name == "gazzetta-mcp"


async def test_instructions_guide_the_assistant(client):
    text = client.instructions
    assert "NON chiedere mai" in text and "parziali" in text and "cicli" in text


async def test_tool_descriptions_say_when_to_use_them(client):
    for tool in await client.list_tools():
        assert "Usalo" in tool.description, tool.name
    tools = {t.name: t for t in await client.list_tools()}
    assert "parziale" in tools["cerca"].description


async def test_lifespan_closes_owned_service(monkeypatch):
    service, _, _, http_client = make_service()
    monkeypatch.setattr("gazzetta_mcp.server.build_service", lambda: service)
    async with Client(create_server()) as c:
        await c.call_tool("rimando_normattiva", {"atto": "legge 5 agosto 2026, n. 140"})
        assert not http_client._http.is_closed
    assert http_client._http.is_closed


def test_version_flag_via_real_process():
    out = subprocess.run(
        [sys.executable, "-m", "gazzetta_mcp.server", "--version"],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert out.stdout.startswith("gazzetta-mcp ")
