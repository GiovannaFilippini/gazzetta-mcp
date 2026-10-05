"""Edge cases of the text cleaning, tipo detection and malformed input."""

from __future__ import annotations

from datetime import date

import pytest

from gazzetta_mcp.models import Serie
from gazzetta_mcp.parsing import GuParser, clean_text, detect_tipo, extract_pre

BASE = "https://www.gazzettaufficiale.it"


def test_empty_input():
    assert clean_text("") == ""
    assert clean_text(" \n \n") == ""
    assert extract_pre(b"") == ""
    assert extract_pre(b"<html><body><pre>   </pre></body></html>") == ""


def test_raw_mode_is_identity():
    s = " \n  Visto  il   x-\ny \n"
    assert clean_text(s, raw=True) == s


def test_rewrap_and_indent_paragraphs():
    s = "  Primo  paragrafo che va\na capo.\n  Secondo paragrafo. \n"
    assert clean_text(s) == "Primo paragrafo che va a capo.\n\nSecondo paragrafo."


def test_blank_line_separates_paragraphs():
    assert clean_text("uno\ndue\n \ntre\n") == "uno due\n\ntre"


def test_centered_headings_kept_on_own_lines():
    s = "  Testo prima.\n \n                               Art. 1 \n \n  1. Testo."
    assert clean_text(s) == "Testo prima.\n\nArt. 1\n\n1. Testo."


def test_list_marker_after_sentence_end_starts_paragraph():
    s = "cosi' stabilito:\na) prima voce;\nb) seconda\nvoce lunga;\nc) fine."
    assert (
        clean_text(s) == "cosi' stabilito:\n\na) prima voce;\n\nb) seconda voce lunga;\n\nc) fine."
    )


def test_list_marker_mid_sentence_is_not_a_break():
    # "n.\n59" style wraps must not be split
    assert clean_text("legge 15 marzo 1997, n.\n59 recante") == "legge 15 marzo 1997, n. 59 recante"


def test_dehyphenate_only_when_word_proven_elsewhere():
    # "amministrazione" appears whole elsewhere -> split word, hyphen removed
    s = "L'amministrazione c'e'. Ma l'ammini-\nstrazione decide."
    assert "l'amministrazione decide." in clean_text(s)


def test_hyphen_kept_when_not_proven():
    out = clean_text("il decreto-\nlegge e' urgente; la parola rara-\nmente")
    assert "decreto-legge" in out
    assert "rara-mente" in out  # unproven: keep the hyphen, never invent a word


def test_hyphen_before_uppercase_or_digit_kept():
    assert clean_text("Friuli-\nVenezia Giulia") == "Friuli-Venezia Giulia"
    assert clean_text("anni 2020-\n2021") == "anni 2020-2021"


def test_space_dash_at_end_of_line_is_not_a_split():
    assert clean_text("voce -\nseguito") == "voce - seguito"


def test_apostrophe_accents_not_touched():
    assert clean_text("e' stato, perche' si'") == "e' stato, perche' si'"


def test_extract_pre_decodes_entities_and_cp1252():
    html = b"<html><body><pre>a &amp; b &lt;c&gt;</pre></body></html>"
    assert extract_pre(html) == "a & b <c>"
    latin = "<pre>perché «x»</pre>".encode("cp1252")
    assert extract_pre(latin) == "perché «x»"


def test_extract_pre_falls_back_to_body():
    assert extract_pre(b"<html><body><p>solo testo</p></body></html>").strip() == "solo testo"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("DECRETO 9 settembre 2026", "DECRETO"),
        ("MINISTERO DELL'ECONOMIA E DELLE FINANZE - DECRETO 7 settembre 2026", "DECRETO"),
        ("CAMERA DEI DEPUTATI - AVVISO", "AVVISO"),
        ("LEGGE 5 agosto 2026, n. 140", "LEGGE"),
        ("DECRETO-LEGGE 1 ottobre 2026, n. 150", "DECRETO-LEGGE"),
        ("DECRETO LEGISLATIVO 2 febbraio 2021, n. 18", "DECRETO LEGISLATIVO"),
        (
            "PRESIDENZA DEL CONSIGLIO DEI MINISTRI DIPARTIMENTO - ORDINANZA 17 settembre 2026",
            "ORDINANZA",
        ),
        ("n. 149 ORDINANZA (Atto di promovimento) 2 luglio 2026", "ORDINANZA"),
        ("COMUNE DI ROMA", None),
        ("", None),
        ("il decreto del tale", None),
    ],
)
def test_detect_tipo(title, expected):
    assert detect_tipo(title) == expected


def test_malformed_inputs_do_not_raise():
    p = GuParser()
    s = p.parse_sommario(b"", Serie.SG, date(2026, 10, 3), 230, BASE + "/")
    assert s.voci == [] and s.link == f"{BASE}/eli/gu/2026/10/03/230/SG/html"
    s = p.parse_sommario(
        b"<html><body>nothing</body></html>", Serie.S4, date(2026, 10, 2), 76, "http://h"
    )
    assert s.voci == [] and s.link_pdf == "https://h/eli/gu/2026/10/02/76/S4/pdf"
    a = p.parse_atto(b"", b"", "26A00001", Serie.SG, date(2026, 1, 2), BASE)
    assert (a.titolo, a.emettitore, a.testo, a.tipo, a.numero_gu) == ("", "", "", None, None)
    assert a.link == f"{BASE}/eli/id/2026/01/02/26A00001/SG"


def test_feed_item_missing_fields():
    xml = (
        b'<rss xmlns:content="http://purl.org/rss/1.0/modules/content/" version="2.0"><channel>'
        b"<link>http://www.gazzettaufficiale.it/eli/gu/2026/10/03/230/SG/html</link>"
        b"<item><title>  A   B </title><content:encoded>testo (26A00001)</content:encoded></item>"
        b"<item><title>no id</title></item>"
        b"</channel></rss>"
    )
    feed = GuParser().parse_feed(xml, Serie.SG)
    assert len(feed.items) == 1
    item = feed.items[0]
    assert (item.codice, item.titolo, item.riassunto) == ("26A00001", "A B", "testo")
    assert item.pubblicato is None and item.data == date(2026, 10, 3)
