"""Table-driven tests for the Normattiva link builder. No network."""

import pytest

from gazzetta_mcp.config import Settings
from gazzetta_mcp.sources.normattiva import NormattivaLinkBuilder

BASE = "https://www.normattiva.it/uri-res/N2Ls?"
DPR = "decreto.del.presidente.della.repubblica"
DPCM = "decreto.del.presidente.del.consiglio.dei.ministri"

CASES = [
    ("legge 5 agosto 2026, n. 140", "legge:2026-08-05;140"),
    ("Legge 5 agosto 2026 n. 140", "legge:2026-08-05;140"),
    ("LEGGE 5 AGOSTO 2026, N. 140", "legge:2026-08-05;140"),
    ("legge n. 140 del 5 agosto 2026", "legge:2026-08-05;140"),
    ("legge 5/8/2026 n. 140", "legge:2026-08-05;140"),
    ("legge 05-08-2026, n.140", "legge:2026-08-05;140"),
    ("L. 5 agosto 2026, n° 140", "legge:2026-08-05;140"),
    ("l. 5 agosto 2026 nº 140", "legge:2026-08-05;140"),
    ("legge 7 agosto 1990, n. 241", "legge:1990-08-07;241"),
    ("legge 1° gennaio 1990, n. 5", "legge:1990-01-01;5"),
    ("legge 1º gennaio 1990 num. 5", "legge:1990-01-01;5"),
    ("D.Lgs. 7 agosto 2026 n. 148", "decreto.legislativo:2026-08-07;148"),
    ("d.lgs. 7 agosto 2026, n.148", "decreto.legislativo:2026-08-07;148"),
    ("dlgs 7 agosto 2026 n. 148", "decreto.legislativo:2026-08-07;148"),
    ("decreto legislativo 7 agosto 2026, n. 148", "decreto.legislativo:2026-08-07;148"),
    ("Decreto Legislativo 30 marzo 2001 n 165", "decreto.legislativo:2001-03-30;165"),
    ("decreto-legge 7 agosto 2026, n. 144", "decreto.legge:2026-08-07;144"),
    ("D.L. 7 agosto 2026 n. 144", "decreto.legge:2026-08-07;144"),
    ("DL 7 agosto 2026, n. 144", "decreto.legge:2026-08-07;144"),
    ("DPR 26 ottobre 1972 n. 633", f"{DPR}:1972-10-26;633"),
    ("D.P.R. 26 ottobre 1972, n. 633", f"{DPR}:1972-10-26;633"),
    ("decreto del Presidente della Repubblica 26 ottobre 1972, n. 633", f"{DPR}:1972-10-26;633"),
    ("d.p.c.m. 9 marzo 2020, n. 11", f"{DPCM}:2020-03-09;11"),
    (
        "decreto del Presidente del Consiglio dei ministri 9 marzo 2020 n. 11",
        f"{DPCM}:2020-03-09;11",
    ),
    ("regio decreto 16 marzo 1942, n. 262", "regio.decreto:1942-03-16;262"),
    ("R.D. 16 marzo 1942 n. 262", "regio.decreto:1942-03-16;262"),
    ("RD 18 giugno 1931, n. 773", "regio.decreto:1931-06-18;773"),
    ("regio decreto-legge 27 novembre 1933, n. 1578", "regio.decreto.legge:1933-11-27;1578"),
    ("R.D.Lgs. 14 aprile 1910 n. 639", "regio.decreto.legislativo:1910-04-14;639"),
    ("legge costituzionale 18 ottobre 2001, n. 3", "legge.costituzionale:2001-10-18;3"),
    ("L. cost. 18 ottobre 2001 n. 3", "legge.costituzionale:2001-10-18;3"),
    ("decreto ministeriale 3 aprile 2013, n. 55", "decreto.ministeriale:2013-04-03;55"),
    # number/year short form (no date); verified live for legge:1990;241
    ("DL 144/2026", "decreto.legge:2026;144"),
    ("l. 241/1990", "legge:1990;241"),
    ("legge 241/1990", "legge:1990;241"),
    ("Legge n. 241/1990", "legge:1990;241"),
    ("legge 241 / 1990", "legge:1990;241"),
    ("D.Lgs. 165/2001", "decreto.legislativo:2001;165"),
    ("dpr 633/1972", f"{DPR}:1972;633"),
    ("  decreto-legge   n. 18/2020 ", "decreto.legge:2020;18"),
]


@pytest.fixture
def linker() -> NormattivaLinkBuilder:
    return NormattivaLinkBuilder()


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_link_for(linker, text, expected):
    res = linker.link_for(text)
    assert res.urn == f"urn:nir:stato:{expected}"
    assert res.link == BASE + res.urn
    assert "non e' una fonte ufficiale" in res.nota
    assert "Gazzetta Ufficiale" in res.nota
    assert "Fonte: Normattiva" in res.nota


def test_short_form_note(linker):
    assert "data esatta" in linker.link_for("l. 241/1990").nota
    assert "data esatta" not in linker.link_for("legge 7 agosto 1990, n. 241").nota


def test_citation_label(linker):
    assert linker.link_for("L. 7 AGOSTO 1990 n°241").atto == "Legge 7 agosto 1990, n. 241"
    assert linker.link_for("DL 144/2026").atto == "Decreto-legge n. 144 del 2026"


@pytest.mark.parametrize("text", ["26G00123", "codice redazionale 26g00123", "GU 26A01234"])
def test_codice_redazionale(linker, text):
    res = linker.link_for(text)
    assert res.urn == ""
    assert res.link == "https://www.normattiva.it/ricerca/semplice"
    assert "non identifica l'atto" in res.nota
    assert "Gazzetta Ufficiale" in res.nota


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "ciao",
        "legge",
        "legge senza numero",
        "legge 5 agosto 2026",
        "legge 31 febbraio 2026, n. 3",
        "legge 5 smarch 2026, n. 3",
        "legge 0/2026",
        "legge 241/1700",
        "decreto 5 agosto 2026, n. 3",
        "241/1990",
    ],
)
def test_unparseable(linker, text):
    with pytest.raises(ValueError, match="Non riesco a interpretare"):
        linker.link_for(text)


def test_custom_base_url():
    s = Settings(normattiva_base_url="https://example.test/")
    res = NormattivaLinkBuilder(s).link_for("legge 241/1990")
    assert res.link == "https://example.test/uri-res/N2Ls?urn:nir:stato:legge:1990;241"
