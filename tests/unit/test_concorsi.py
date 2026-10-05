from __future__ import annotations

from datetime import date

import pytest

from gazzetta_mcp.concorsi import classify, estrai_posti, keyword_matcher
from gazzetta_mcp.models import Serie
from gazzetta_mcp.parsing import parse_sommario

from ._service_helpers import FIX


@pytest.mark.parametrize(
    ("titolo", "expected"),
    [
        (
            "Concorso pubblico, per titoli ed esami, per la copertura di un posto di infermiere",
            "bando",
        ),
        ("Conferimento, per titoli e colloquio, di una borsa di ricerca", "bando"),
        ("Mobilita' volontaria nazionale, per titoli e colloquio, per un posto", "bando"),
        ("Avviamento numerico a selezione per la copertura di un posto", "bando"),
        ("Stabilizzazione del personale precario dirigenziale", "bando"),
        ("Ammissione al corso di dottorato di ricerca in «Sistema agro-alimentare»", "bando"),
        ("Procedura di selezione per la chiamata di un professore di ruolo", "bando"),
        # a call that merely mentions other words stays a call
        (
            "Concorso pubblico per un posto riservato ai vincitori e agli idonei di altro concorso",
            "bando",
        ),
        ("Concorso pubblico, graduatoria e commissione come da regolamento, per un posto", "bando"),
        ("Riapertura dei termini del conferimento a dirigente medico", "riapertura_termini"),
        ("Proroga dei termini di presentazione delle domande", "proroga"),
        ("Diario della prova scritta del concorso pubblico", "diario_prove"),
        ("Diario delle prove d'esame del concorso pubblico", "diario_prove"),
        ("Calendario delle prove del concorso", "diario_prove"),
        ("Graduatoria finale del concorso pubblico", "esito_graduatoria"),
        ("Approvazione atti della procedura di selezione per la chiamata", "esito_graduatoria"),
        ("Approvazione della graduatoria del concorso", "esito_graduatoria"),
        ("Annullamento del concorso pubblico, per titoli ed esami", "rettifica_annullamento"),
        ("Avviso di rettifica del bando di concorso", "rettifica_annullamento"),
        ("Revoca della procedura di selezione", "rettifica_annullamento"),
        ("Modifica della composizione della Commissione esaminatrice del concorso", "commissione"),
        (
            "Accettazione delle dimissioni di un componente dalla commissione giudicatrice",
            "commissione",
        ),
        ("Cancellazione dal registro dei revisori legali di ventisei revisori", "altro"),
        ("", "altro"),
    ],
)
def test_classify(titolo, expected):
    assert classify(titolo) == expected


@pytest.mark.parametrize(
    ("titolo", "expected"),
    [
        ("per la copertura di un posto di infermiere", 1),
        ("a venti posti di Ragioniere", 20),
        ("per la copertura di venti posti di infermiere", 20),
        ("per la copertura di sette posti di assistente", 7),
        ("copertura di ventuno posti", 21),
        ("copertura di ventotto posti", 28),
        ("copertura di trentatre posti", 33),
        ("copertura di quarantasei posti", 46),
        ("copertura di cento posti", 100),
        ("copertura di n. 5 posti di istruttore", 5),
        ("copertura di 12 posti", 12),
        ("la copertura di tre posti, area dei funzionari", 3),
        ("Conferimento di una borsa di ricerca", None),
        ("dieci professori di seconda fascia", None),
        ("posti: n. 8", 8),
        ("", None),
    ],
)
def test_estrai_posti(titolo, expected):
    assert estrai_posti(titolo) == expected


def test_keyword_matcher_tolerates_plural_and_accents():
    m = keyword_matcher("infermiere")
    assert m("copertura di venti posti di infermiere")
    assert m("posti di INFERMIERI")
    assert m("dirigente delle professioni sanitarie, area infermieristica")
    assert not m("posti di medico")
    both = keyword_matcher("dirigente medico")
    assert both("un posto di dirigente medico, disciplina di cardiologia")
    assert not both("un posto di dirigente amministrativo")
    assert keyword_matcher("oss")("posti di OSS")
    assert not keyword_matcher("oss")("posti di ossetrico")  # short words: whole word only
    assert keyword_matcher("Università")("UNIVERSITA' DI TRENTO")


def test_classification_of_the_real_s4_issue():
    raw = (FIX / "sommario_s4_2026-10-02_76.html").read_bytes()
    som = parse_sommario(raw, Serie.S4, date(2026, 10, 2), 76, "https://www.gazzettaufficiale.it")
    kinds = {}
    for v in som.voci:
        kinds.setdefault(classify(v.titolo), []).append(v)
    assert len(kinds["bando"]) > 40
    assert {"diario_prove", "esito_graduatoria", "commissione", "rettifica_annullamento"} <= set(
        kinds
    )
    assert all(v.titolo.startswith("Diario") for v in kinds["diario_prove"])
    assert all(v.titolo.startswith("Annullamento") for v in kinds["rettifica_annullamento"])
    # 20 posts of nurse in the sample
    posti = [estrai_posti(v.titolo) for v in kinds["bando"] if "infermiere" in v.titolo]
    assert posti == [20]
