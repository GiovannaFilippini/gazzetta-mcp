from __future__ import annotations

import re

import pytest
from fastmcp import Client, FastMCP

from gazzetta_mcp.prompts import register_prompts
from gazzetta_mcp.server import create_server

from ._service_helpers import make_service

ARGS = {
    "riassumi_atto": {"atto": "legge 5 agosto 2026, n. 140"},
    "confronta_decreti": {"primo_atto": "decreto A", "secondo_atto": "decreto B"},
    "concorsi_per_me": {"profilo": "infermiere", "regione": "Lazio"},
    "cosa_e_uscito": {"periodo": "questa settimana"},
    "aggiornamenti_su": {"argomento": "bonus affitti"},
}
# The three tools written in parallel; they exist only after integration.
NEW_TOOLS = {"scadenze_concorsi", "testo_vigente", "novita_argomento"}
OLD_TOOLS = {
    "ultime_pubblicazioni",
    "sommario",
    "leggi_atto",
    "cerca",
    "cerca_concorsi",
    "rimando_normattiva",
}
ALL_TOOLS = NEW_TOOLS | OLD_TOOLS


@pytest.fixture
async def client():
    mcp = FastMCP("test")
    register_prompts(mcp)
    async with Client(mcp) as c:
        yield c


async def _text(client, name):
    return (await client.get_prompt(name, ARGS[name])).messages[0].content.text


async def test_prompts_are_listed_with_expected_arguments(client):
    prompts = {p.name: p for p in await client.list_prompts()}
    assert set(prompts) == set(ARGS)
    for name, p in prompts.items():
        assert p.description
        assert {a.name for a in p.arguments} == set(ARGS[name])
    required = {a.name for a in prompts["concorsi_per_me"].arguments if a.required}
    assert required == {"profilo"}


@pytest.mark.parametrize("name", sorted(ARGS))
async def test_text_has_disclaimer_rules_and_user_words(client, name):
    text = await _text(client, name)
    assert "non ufficiale" in text and "gazzettaufficiale.it" in text
    assert "NON chiedergli mai" in text and "parziali" in text and "link ufficiale" in text
    assert "professionista" in text
    assert all(v in text for v in ARGS[name].values())


async def test_every_cited_tool_exists(client):
    for name in ARGS:
        text = await _text(client, name)
        for word in re.findall(r"\b[a-z]+_[a-z_]+\b", text):
            assert word in ALL_TOOLS, (name, word)


async def test_old_tool_names_match_the_real_server():
    service, *_ = make_service()
    async with Client(create_server(service)) as c:
        real = {t.name for t in await c.list_tools()}
    assert OLD_TOOLS <= real <= ALL_TOOLS
