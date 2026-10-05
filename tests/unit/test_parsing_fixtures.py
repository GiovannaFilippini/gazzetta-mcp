"""Parser tests on the real samples in tests/fixtures/real (no network)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from gazzetta_mcp.models import Serie
from gazzetta_mcp.parsing import GuParser, ParseError

F = Path(__file__).parent.parent / "fixtures" / "real"
BASE = "https://www.gazzettaufficiale.it"
P = GuParser()


def read(name: str) -> bytes:
    return (F / name).read_bytes()


@pytest.mark.parametrize(
    ("name", "serie", "numero", "data", "n_items"),
    [
        ("rss_SG.xml", Serie.SG, 230, date(2026, 10, 3), 17),
        ("rss_S4.xml", Serie.S4, 76, date(2026, 10, 2), 69),
        ("rss_S5.xml", Serie.S5, 112, date(2026, 10, 2), 4),
        ("rss_S1.xml", Serie.S1, 39, date(2026, 9, 30), 7),
    ],
)
def test_feed_fixtures(name, serie, numero, data, n_items):
    feed = P.parse_feed(read(name), serie)
    assert (feed.serie, feed.numero, feed.data) == (serie, numero, data)
    assert feed.link.startswith("https://")
    assert len(feed.items) == n_items
    for item in feed.items:
        assert item.codice and item.titolo
        assert item.link.startswith("https://")
        assert item.link.endswith(f"/{item.codice}/{serie.value}")
        assert f"({item.codice})" not in item.riassunto
        assert "  " not in item.riassunto and "\n" not in item.riassunto
        assert item.pubblicato is not None


def test_feed_first_item_sg():
    item = P.parse_feed(read("rss_SG.xml"), Serie.SG).items[0]
    assert item.codice == "26A05182"
    assert item.titolo.endswith("DECRETO 9 settembre 2026")
    assert item.riassunto.startswith("Aggiornamento del registro nazionale")
    assert item.riassunto.endswith("propagazione vegetale.")
    assert item.pubblicato.year == 2026


def test_feed_alphanumeric_code_s5():
    item = P.parse_feed(read("rss_S5.xml"), Serie.S5).items[0]
    assert item.codice == "TX26BFF411"
    assert item.riassunto == "Variante in corso d'opera - CIG 962208E32"


def test_sommario_sg():
    s = P.parse_sommario(
        read("sommario_sg_2026-10-03_230.html"), Serie.SG, date(2026, 10, 3), 230, BASE
    )
    assert s.link == f"{BASE}/eli/gu/2026/10/03/230/SG/html"
    assert s.link_pdf == f"{BASE}/eli/gu/2026/10/03/230/SG/pdf"
    assert len(s.voci) == 17
    v = s.voci[0]
    assert v.codice == "26A05182"
    assert v.emettitore.startswith("MINISTERO DELL'AGRICOLTURA")
    assert v.rubrica == "DECRETI, DELIBERE E ORDINANZE MINISTERIALI"
    assert v.tipo == "DECRETO"
    assert v.link == f"{BASE}/eli/id/2026/10/03/26A05182/SG"
    assert v.titolo.startswith("Aggiornamento del registro") and "(26A05182)" not in v.titolo
    assert len({x.codice for x in s.voci}) == len(s.voci)
    assert all(x.emettitore and x.rubrica and x.titolo for x in s.voci)
    # the last rubrica seen applies to the following entries
    assert {x.rubrica for x in s.voci} > {"DECRETI, DELIBERE E ORDINANZE MINISTERIALI"}


def test_sommario_s4():
    s = P.parse_sommario(
        read("sommario_s4_2026-10-02_76.html"), Serie.S4, date(2026, 10, 2), 76, BASE
    )
    assert len(s.voci) == 69
    v = s.voci[0]
    assert (v.codice, v.tipo, v.emettitore, v.rubrica) == (
        "26E05478",
        "AVVISO",
        "CAMERA DEI DEPUTATI",
        "ORGANI COSTITUZIONALI",
    )
    assert v.link.endswith("/eli/id/2026/10/02/26E05478/S4")
    assert all(x.link.endswith(f"/{x.codice}/S4") for x in s.voci)


def test_atto_sg_full():
    a = P.parse_atto(
        read("atto_scheda_26A05182_sg.html"),
        read("atto_testo_26A05182_sg.html"),
        "26A05182",
        Serie.SG,
        date(2026, 10, 3),
        BASE,
    )
    assert a.tipo == "DECRETO"
    assert a.emettitore.startswith("MINISTERO DELL'AGRICOLTURA")
    assert a.titolo.startswith("DECRETO 9 settembre 2026 - Aggiornamento del registro")
    assert a.numero_gu == 230
    assert a.link == f"{BASE}/eli/id/2026/10/03/26A05182/SG"
    assert a.testo.startswith("IL DIRETTORE GENERALE\ndello sviluppo rurale\n\nVisto il decreto")
    assert "Decreta:\n\nArt. 1\n\n1. Ai sensi" in a.testo
    assert "«Riforma dell'organizzazione del Governo" in a.testo
    # accents are NOT guessed: GU ASCII apostrophes stay as they are
    assert "con il quale e' stato istituito" in a.testo
    assert "  " not in a.testo
    assert a.testo.count("\n\n") > 20


def test_atto_content_is_preserved_word_for_word():
    from gazzetta_mcp.parsing import extract_pre

    raw = extract_pre(read("atto_testo_26A05182_sg.html"))
    cleaned = P.parse_atto(
        b"", read("atto_testo_26A05182_sg.html"), "X", Serie.SG, date(2026, 1, 1), BASE
    ).testo
    assert cleaned.split() == raw.split()


def test_atto_raw_mode_returns_pre_unmodified():
    from gazzetta_mcp.parsing import extract_pre

    testo = read("atto_testo_26A05182_sg.html")
    a = GuParser(raw_text=True).parse_atto(b"", testo, "X", Serie.SG, date(2026, 1, 1), BASE)
    assert a.testo == extract_pre(testo)
    assert "  Visto il decreto  legislativo" in a.testo


def test_atto_s4_scheda_only():
    a = P.parse_atto(
        read("atto_scheda_26E05478_s4.html"), b"", "26E05478", Serie.S4, date(2026, 10, 2), BASE
    )
    assert a.tipo == "AVVISO"
    assert a.emettitore == "CAMERA DEI DEPUTATI"
    assert a.titolo.startswith("AVVISO - Modifica della composizione")
    assert a.testo == ""
    assert a.numero_gu == 76


def test_feed_errors_and_empty_channel():
    with pytest.raises(ParseError):
        P.parse_feed(b"", Serie.SG)
    with pytest.raises(ParseError):
        P.parse_feed(b"<not xml", Serie.SG)
    with pytest.raises(ParseError):
        P.parse_feed(b"<rss><channel><link>http://x/y</link></channel></rss>", Serie.SG)
    empty = (
        b'<rss version="2.0"><channel><link>http://www.gazzettaufficiale.it/eli/gu/2026/10/03/230/SG/html'
        b"</link></channel></rss>"
    )
    feed = P.parse_feed(empty, Serie.SG)
    assert feed.items == [] and feed.numero == 230 and feed.link.startswith("https://")
