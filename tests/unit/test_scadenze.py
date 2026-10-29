from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from gazzetta_mcp.models import Serie
from gazzetta_mcp.parsing import GuParser
from gazzetta_mcp.scadenze import (
    METODO_DATA,
    METODO_GIORNI,
    METODO_NESSUNO,
    festivita,
    pasqua,
    primo_giorno_utile,
    ricava_scadenza,
)

FIX = Path(__file__).parent.parent / "fixtures" / "scadenze"
GU = " nella Gazzetta Ufficiale della Repubblica italiana - 4a Serie speciale «Concorsi ed esami»."


@pytest.mark.parametrize(
    ("anno", "atteso"),
    [
        (2024, date(2024, 3, 31)),
        (2025, date(2025, 4, 20)),
        (2026, date(2026, 4, 5)),
        (2027, date(2027, 3, 28)),
        (2028, date(2028, 4, 16)),
    ],
)
def test_pasqua(anno, atteso):
    assert pasqua(anno) == atteso


def test_festivita_nazionali():
    feste = festivita(2026)
    assert len(feste) == 11
    assert feste[date(2026, 4, 6)] == "Lunedi' dell'Angelo"
    for giorno in [(1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15), (11, 1), (12, 8), (12, 25)]:
        assert date(2026, *giorno) in feste
    assert date(2026, 12, 26) in feste


def test_primo_giorno_utile_non_sposta_un_giorno_normale():
    assert primo_giorno_utile(date(2026, 10, 15)) == (date(2026, 10, 15), "")
    # the Saturday is a working day unless the text says otherwise
    assert primo_giorno_utile(date(2026, 10, 17)) == (date(2026, 10, 17), "")


def test_primo_giorno_utile_sabato_festivo_su_richiesta():
    giorno, motivo = primo_giorno_utile(date(2026, 10, 17), sabato_festivo=True)
    assert giorno == date(2026, 10, 19)
    assert "sabato" in motivo and "domenica" in motivo


@pytest.mark.parametrize(
    ("pubblicazione", "atteso", "motivo"),
    [
        (date(2026, 3, 20), date(2026, 4, 20), "domenica"),  # 19 April is a Sunday
        (date(2026, 3, 7), date(2026, 4, 7), "Lunedi' dell'Angelo"),
        (date(2026, 3, 26), date(2026, 4, 27), "Liberazione"),  # Sat holiday, then Sunday
        (date(2026, 5, 3), date(2026, 6, 3), "Repubblica"),
        (date(2026, 10, 2), date(2026, 11, 2), "Ognissanti"),
        (date(2026, 12, 2), date(2027, 1, 2), "Capodanno"),  # Saturday: not moved further
        (date(2026, 9, 25), date(2026, 10, 26), "domenica"),
    ],
)
def test_trenta_giorni_con_festivi(pubblicazione, atteso, motivo):
    sc = ricava_scadenza(
        "scade al trentesimo giorno successivo alla pubblicazione"
        + GU
        + " Le domande di partecipazione si presentano online.",
        pubblicazione,
    )
    assert sc.metodo == METODO_GIORNI
    assert sc.giorni == 30
    assert sc.data == atteso
    assert sc.data_nominale is not None and sc.data_nominale != sc.data
    assert motivo in sc.motivo_spostamento


@pytest.mark.parametrize(
    ("pubblicazione", "atteso"),
    [
        (date(2028, 1, 30), date(2028, 2, 29)),  # leap year
        (date(2027, 2, 10), date(2027, 3, 12)),  # same dates, not a leap year
        (date(2028, 2, 10), date(2028, 3, 11)),  # leap year, Saturday stays
        (date(2026, 12, 15), date(2027, 1, 14)),  # change of year
        (date(2026, 10, 5), date(2026, 11, 4)),  # change of month
    ],
)
def test_trenta_giorni_calendario(pubblicazione, atteso):
    sc = ricava_scadenza(
        "Il termine per la presentazione delle domande scade il trentesimo giorno successivo "
        "alla data di pubblicazione del presente avviso" + GU,
        pubblicazione,
    )
    assert sc.data == atteso
    assert sc.motivo_spostamento == ""


def test_sabato_festivo_se_lo_dice_il_bando():
    testo = (
        "Le domande vanno presentate entro il trentesimo giorno successivo alla pubblicazione"
        + GU
        + " Se il termine cade di sabato o in un giorno festivo e' prorogato al giorno seguente."
    )
    # 2026-12-02 + 30 = Friday 1 January (holiday): the nearest date is Saturday 2 January;
    # the text speaks about Saturdays, so it is flagged and the Monday is named as the alternative
    sc = ricava_scadenza(testo, date(2026, 12, 2))
    assert sc.data == date(2027, 1, 2)
    assert sc.incerta
    assert "2027-01-04" in sc.dettaglio


FORMULE = [
    ("entro trenta giorni dalla data di pubblicazione del presente avviso" + GU, 30),
    ("entro 30 giorni dalla pubblicazione del presente estratto" + GU, 30),
    ("entro 30 (trenta) giorni naturali e consecutivi dalla pubblicazione" + GU, 30),
    ("entro il 30° giorno successivo alla pubblicazione del bando" + GU, 30),
    ("entro il trentesimo giorno successivo alla pubblicazione" + GU, 30),
    ("entro quindici giorni dalla pubblicazione del presente avviso" + GU, 15),
    ("entro il quindicesimo giorno dalla pubblicazione" + GU, 15),
    ("entro venti giorni dalla data di pubblicazione dell'avviso" + GU, 20),
    ("entro il ventesimo giorno successivo alla pubblicazione" + GU, 20),
    ("termine di quarantacinque giorni dalla pubblicazione" + GU, 45),
    ("entro il quarantacinquesimo giorno successivo alla pubblicazione" + GU, 45),
    ("entro sessanta giorni dalla pubblicazione" + GU, 60),
    ("entro il ventunesimo giorno successivo alla pubblicazione" + GU, 21),
    (
        (
            "Dal giorno successivo a quello della pubblicazione del presente avviso nella Gazzetta "
            "Ufficiale decorre il termine perentorio di trenta giorni per la presentazione delle "
            "domande di partecipazione."
        ),
        30,
    ),
    (
        "La domanda deve essere inviata entro 10 giorni dalla pubblicazione del presente avviso"
        + GU,
        10,
    ),
]


@pytest.mark.parametrize(("testo", "giorni"), FORMULE)
def test_formule_in_giorni(testo, giorni):
    pub = date(2026, 6, 9)  # +10 .. +60 never land on a holiday except those moved below
    sc = ricava_scadenza("Le domande di partecipazione vanno presentate " + testo, pub)
    assert sc.metodo == METODO_GIORNI
    assert sc.giorni == giorni
    assert sc.data_nominale == date.fromordinal(pub.toordinal() + giorni)
    # only the wording that is not the standard "del presente avviso" may make it uncertain
    assert not sc.incerta or "non e' quella standard" in sc.dettaglio


def test_la_data_non_si_ricava_senza_riferimento_alla_gazzetta():
    # "30 days from the publication on the website of the body": the date of the GU is useless
    testo = (
        "Le domande di partecipazione vanno presentate entro 30 giorni dalla pubblicazione "
        "del bando sul sito dell'ente."
    )
    assert ricava_scadenza(testo, date(2026, 10, 2)).metodo == METODO_NESSUNO


def test_termini_diversi_dal_termine_delle_domande_sono_ignorati():
    testo = (
        "Pubblicato nella Gazzetta Ufficiale. Il calendario delle prove sara' reso noto con "
        "un preavviso di 20 giorni lavorativi prima della prova."
    )
    assert ricava_scadenza(testo, date(2026, 10, 2)).metodo == METODO_NESSUNO


def test_giorni_lavorativi_non_sono_la_formula():
    testo = "domanda entro 15 giorni lavorativi dalla pubblicazione nella Gazzetta Ufficiale"
    assert ricava_scadenza(testo, date(2026, 10, 2)).metodo == METODO_NESSUNO


def test_termini_in_conflitto_sono_segnalati():
    testo = (
        "Le domande di partecipazione vanno presentate entro il trentesimo giorno successivo "
        "alla pubblicazione nella Gazzetta Ufficiale. I candidati residenti all'estero hanno "
        "quarantacinque giorni dalla pubblicazione nella Gazzetta Ufficiale per le domande."
    )
    sc = ricava_scadenza(testo, date(2026, 6, 9))
    assert sc.incerta
    assert sc.giorni == 30
    assert "controlla il bando" in sc.dettaglio


def test_prevale_la_formula_del_presente_avviso():
    testo = (
        "Il precedente bando, pubblicato nella Gazzetta Ufficiale, fissava il termine delle "
        "domande a quindici giorni dalla pubblicazione. "
        + "Il resto del testo descrive i requisiti. "
        * 6
        + "Con il presente avviso le domande di "
        "partecipazione si presentano entro il trentesimo giorno successivo alla pubblicazione "
        "del presente avviso nella Gazzetta Ufficiale."
    )
    sc = ricava_scadenza(testo, date(2026, 6, 9))
    assert sc.giorni == 30 and sc.incerta


@pytest.mark.parametrize(
    ("testo", "atteso"),
    [
        (
            "Il termine per la presentazione delle domande scade il 15 novembre 2026.",
            date(2026, 11, 15),
        ),
        (
            "Le domande dovranno pervenire entro le ore 12,00 del 20 novembre 2026.",
            date(2026, 11, 20),
        ),
        (
            "La scadenza per la presentazione delle domande e' mercoledi' 18 novembre 2026.",
            date(2026, 11, 18),
        ),
        ("Domande di partecipazione entro il 1° dicembre 2026.", date(2026, 12, 1)),
        ("Le istanze vanno presentate entro il 20/11/2026.", date(2026, 11, 20)),
        ("Le istanze vanno presentate entro il 20.11.2026.", date(2026, 11, 20)),
        (
            "Termini di presentazione delle domande: da lunedi' 21 settembre 2026 a domenica 11 ottobre 2026.",
            date(2026, 10, 11),
        ),
    ],
)
def test_data_esplicita(testo, atteso):
    sc = ricava_scadenza(testo, date(2026, 10, 2))
    assert sc.metodo == METODO_DATA
    assert sc.data == atteso
    assert sc.giorni is None and sc.motivo_spostamento == ""


def test_data_esplicita_non_si_sposta_sul_festivo():
    sc = ricava_scadenza("Le domande scadono il 25 dicembre 2026.", date(2026, 10, 2))
    assert sc.data == date(2026, 12, 25)


def test_date_di_atti_o_passate_non_sono_scadenze():
    testo = (
        "Con decreto n. 12 del 3 ottobre 2026 e' indetto un concorso. Il termine per la "
        "presentazione delle domande e' stabilito dal bando integrale, pubblicato nel "
        "Bollettino Ufficiale del 30 settembre 2026."
    )
    assert ricava_scadenza(testo, date(2026, 10, 2)).metodo == METODO_NESSUNO
    vecchia = "Termine per la presentazione delle domande: entro il 16 dicembre 2024."
    assert ricava_scadenza(vecchia, date(2026, 10, 2)).metodo == METODO_NESSUNO


def test_data_inesistente_non_e_una_scadenza():
    sc = ricava_scadenza("Le domande scadono il 31 novembre 2026.", date(2026, 10, 2))
    assert sc.metodo == METODO_NESSUNO


@pytest.mark.parametrize(
    "testo", ["", "   ", "Il bando integrale e' pubblicato sul sito dell'ente."]
)
def test_nessuna_scadenza(testo):
    sc = ricava_scadenza(testo, date(2026, 10, 2))
    assert sc.data is None
    assert sc.metodo == METODO_NESSUNO
    assert sc.dettaglio


# Real texts of the 4th series (published 2026-10-02): tests/fixtures/scadenze/
REALI = [
    (
        "26E05253",
        METODO_GIORNI,
        date(2026, 11, 2),
    ),  # university chairs: "termine perentorio di trenta giorni"
    ("26E05257", METODO_DATA, date(2026, 10, 12)),  # PhD: explicit date
    ("26E05258", METODO_DATA, date(2026, 10, 11)),  # municipality: "da ... a ..."
    ("26E05265", METODO_GIORNI, date(2026, 11, 2)),  # nurses: "scade al trentesimo giorno"
    ("26E05271", METODO_GIORNI, date(2026, 11, 2)),  # "entro trenta giorni dal giorno successivo"
    ("26E05294", METODO_GIORNI, date(2026, 11, 2)),  # reopening: old dates are in the text
    ("26E05295", METODO_NESSUNO, None),  # "entro il termine perentorio stabilito dal bando"
    ("26E05302", METODO_GIORNI, date(2026, 10, 17)),  # CNR grant: 15 days
    ("26E05303", METODO_GIORNI, date(2026, 11, 2)),  # hospital: "ore 12,00 del trentesimo giorno"
    ("26E05465", METODO_GIORNI, date(2026, 10, 17)),  # CNR grants: 15 days + festive rule
]


@pytest.fixture(scope="module")
def testi_reali():
    parser = GuParser()
    out = {}
    for codice, _, _ in REALI:
        raw = (FIX / f"testo_{codice}.html").read_bytes()
        out[codice] = parser.parse_atto(
            b"", raw, codice, Serie.S4, date(2026, 10, 2), "https://www.gazzettaufficiale.it"
        ).testo
    return out


@pytest.mark.parametrize(("codice", "metodo", "atteso"), REALI)
def test_testi_reali(testi_reali, codice, metodo, atteso):
    sc = ricava_scadenza(testi_reali[codice], date(2026, 10, 2))
    assert sc.metodo == metodo
    assert sc.data == atteso
    assert not sc.incerta


def test_slittamento_dei_testi_reali(testi_reali):
    # 2 October + 30 days = Sunday 1 November (All Saints): the deadline moves to Monday
    sc = ricava_scadenza(testi_reali["26E05271"], date(2026, 10, 2))
    assert sc.data_nominale == date(2026, 11, 1)
    assert sc.data == date(2026, 11, 2)
    assert "Ognissanti" in sc.motivo_spostamento


@pytest.mark.parametrize(
    "testo",
    [
        (
            "Le domande vanno presentate entro 30 giorni dalla data di pubblicazione del bando "
            "sul sito istituzionale dell'ente. L'estratto e' pubblicato nella Gazzetta Ufficiale."
        ),
        (
            "Le domande di partecipazione entro 30 giorni dalla pubblicazione sul sito dell'ente "
            "(albo online). L'estratto e' stato pubblicato nella Gazzetta Ufficiale."
        ),
        (
            "Presentazione delle domande entro 60 giorni dalla pubblicazione sul sito web "
            "dell'azienda; avviso di pubblicazione nella Gazzetta Ufficiale."
        ),
        (
            "Le domande entro 15 giorni dalla pubblicazione sull'albo pretorio; l'estratto e' in "
            "Gazzetta Ufficiale."
        ),
        (
            "L'estratto e' pubblicato nella Gazzetta Ufficiale. Le domande vanno presentate "
            "entro 30 giorni dalla pubblicazione sul sito dell'ente."
        ),
    ],
)
def test_termine_dal_sito_dell_ente_non_e_calcolato_dalla_gazzetta(testo):
    # the term starts from another date: a sure but wrong date would be worse than none
    sc = ricava_scadenza(testo, date(2026, 10, 20))
    assert sc.data is None
    assert sc.metodo == METODO_NESSUNO
    assert "sito" in sc.dettaglio


def test_termine_del_ricorso_non_e_la_scadenza_delle_domande():
    testo = (
        "Le domande di partecipazione si presentano online. Avverso il bando e' ammesso "
        "ricorso al TAR entro 60 giorni dalla pubblicazione nella Gazzetta Ufficiale."
    )
    sc = ricava_scadenza(testo, date(2026, 10, 20))
    assert sc.data is None
    assert sc.metodo == METODO_NESSUNO


def test_il_termine_del_ricorso_non_cancella_quello_delle_domande():
    testo = (
        "Le domande di partecipazione vanno presentate entro il trentesimo giorno successivo "
        "alla pubblicazione del presente estratto nella Gazzetta Ufficiale. Avverso il bando e' "
        "ammesso ricorso al TAR entro 60 giorni dalla pubblicazione nella Gazzetta Ufficiale."
    )
    sc = ricava_scadenza(testo, date(2026, 10, 20))
    assert sc.data == date(2026, 11, 19)
    assert sc.giorni == 30
    assert not sc.incerta


@pytest.mark.parametrize(
    "testo",
    [
        (
            "Il bando e' pubblicato sul sito dell'ente e in Gazzetta Ufficiale; le domande di "
            "partecipazione entro 30 giorni dalla pubblicazione."
        ),
        (
            "Le domande di partecipazione entro 30 giorni dalla pubblicazione del presente bando "
            "sul BUR (bollettino regionale). Estratto in Gazzetta Ufficiale."
        ),
        (
            "Le domande di partecipazione entro 30 giorni dalla pubblicazione sul Bollettino "
            "Ufficiale della Regione Lombardia, il cui avviso e' in Gazzetta Ufficiale."
        ),
        (
            "Le domande di partecipazione entro 30 giorni dalla pubblicazione sulla Gazzetta "
            "Ufficiale dell'Unione europea."
        ),
        (
            "Il bando e' pubblicato nella GUUE. Le domande di partecipazione entro 30 giorni "
            "dalla pubblicazione nella Gazzetta Ufficiale - 4a serie speciale."
        ),
    ],
)
def test_altre_pubblicazioni_non_sono_la_gazzetta_italiana(testo):
    # website, regional bulletin or EU gazette: the date of the Italian GU would be wrong
    sc = ricava_scadenza(testo, date(2026, 10, 2))
    assert sc.data is None
    assert sc.metodo == METODO_NESSUNO


@pytest.mark.parametrize(
    "testo",
    [
        (
            "Le domande di partecipazione si presentano online. Entro 60 giorni dalla "
            "pubblicazione nella Gazzetta Ufficiale puo' essere proposto ricorso al TAR."
        ),
        (
            "Le domande di partecipazione si presentano online. Entro 120 giorni dalla "
            "pubblicazione nella Gazzetta Ufficiale e' ammesso ricorso straordinario al "
            "Presidente della Repubblica."
        ),
    ],
)
def test_ricorso_dopo_la_cifra_non_da_mai_una_data_sicura(testo):
    sc = ricava_scadenza(testo, date(2026, 10, 2))
    assert sc.data is None or sc.incerta


# -- third review: Saturday, non-calendar days, other bulletins, other terms ---------------------

SABATO = (
    "Le domande devono essere presentate entro il trentesimo giorno successivo alla "
    "pubblicazione del presente avviso" + GU
)


@pytest.mark.parametrize(
    "frase",
    [
        "Il sabato non festivo e' giorno utile per l'invio.",
        "Il termine non si sospende il sabato e i giorni festivi.",
        "Resta inteso che il sabato e' giorno lavorativo per l'invio telematico.",
        "Il sabato e' lavorativo.",
        "I termini sono consecutivi, compresi il sabato e i giorni festivi.",
        "Le sedute della commissione non si tengono il sabato ne' in altri giorni festivi.",
    ],
)
def test_il_sabato_non_sposta_mai_la_scadenza_senza_avviso(frase):
    # 2026-10-15 + 30 = Saturday 14 November: the nearest date is the Saturday, and the text
    # talks about Saturdays, so it is flagged: it is never moved to Monday as if it were sure
    sc = ricava_scadenza(SABATO + " " + frase, date(2026, 10, 15))
    assert sc.data == date(2026, 11, 14)
    assert sc.incerta
    assert "2026-11-16" in sc.dettaglio


@pytest.mark.parametrize(
    "termine",
    [
        "entro il trentesimo giorno lavorativo successivo alla pubblicazione",
        "entro 30 giorni, esclusi i festivi, dalla pubblicazione",
        "entro 30 giorni non festivi dalla pubblicazione",
        "entro 30 giorni utili dalla pubblicazione",
        "entro 30 giorni di lavoro dalla pubblicazione",
        "entro 30 giorni, esclusi i sabati e i festivi, dalla pubblicazione",
        "entro 15 giorni lavorativi dalla pubblicazione",
    ],
)
def test_giorni_non_di_calendario_non_si_calcolano(termine):
    testo = "Le domande di partecipazione vanno presentate " + termine + GU
    sc = ricava_scadenza(testo, date(2026, 10, 13))
    assert sc.data is None


@pytest.mark.parametrize(
    "fonte",
    [
        "nella Gazzetta Ufficiale della Regione siciliana",
        "sul B.U.R.P.",
        "sul Bollettino della Provincia autonoma di Bolzano",
        "nel Foglio degli annunzi legali",
        "su due quotidiani a diffusione nazionale",
        "nella sezione Amministrazione trasparente",
        "nella Gazzetta Ufficiale della Regione autonoma Friuli Venezia Giulia",
    ],
)
def test_altre_fonti_non_sono_la_gazzetta_italiana_nemmeno_cosi(fonte):
    testo = (
        f"Estratto pubblicato nella Gazzetta Ufficiale. Le domande di partecipazione entro 30 "
        f"giorni dalla pubblicazione {fonte}."
    )
    assert ricava_scadenza(testo, date(2026, 10, 13)).data is None


@pytest.mark.parametrize(
    "testo",
    [
        (
            "Le domande di partecipazione si presentano online e il colloquio si terra' entro il "
            "20 dicembre 2026."
        ),
        "Le domande vanno presentate online. La prova orale si terra' entro il 20 dicembre 2026.",
    ],
)
def test_data_di_colloquio_o_prova_non_e_la_scadenza_delle_domande(testo):
    assert ricava_scadenza(testo, date(2026, 12, 7)).data is None


@pytest.mark.parametrize(
    "testo",
    [
        "Le domande vanno presentate entro il 20 novembre 2026. Il diario delle prove sara' "
        "reso noto con pubblicazione" + GU + " almeno 15 giorni prima.",
        "Le domande scadono il 20 novembre 2026. Con la pubblicazione" + GU + " verra' dato un "
        "preavviso di almeno 15 giorni per le prove.",
        "Il termine per le domande e' il 20 novembre 2026. I requisiti sono verificati entro "
        "30 giorni dalla pubblicazione della graduatoria" + GU,
        "Le domande vanno presentate entro il 18 novembre 2026. Eventuali osservazioni entro "
        "10 giorni dalla pubblicazione" + GU,
        "Il vincitore deve prendere servizio entro 30 giorni dalla pubblicazione della "
        "graduatoria" + GU + " Le domande di partecipazione si presentano online.",
    ],
)
def test_altri_termini_non_cancellano_la_data_delle_domande(testo):
    sc = ricava_scadenza(testo, date(2026, 10, 13))
    assert sc.data in (None, date(2026, 11, 18), date(2026, 11, 20))


@pytest.mark.parametrize(
    "testo",
    [
        "Si comunica che il termine di 30 giorni dalla pubblicazione del bando" + GU + " per le "
        "domande di partecipazione e' prorogato al 30 novembre 2026.",
        "Il termine per la presentazione delle domande e' prorogato di 15 giorni dalla "
        "pubblicazione del presente avviso" + GU,
        "La prova scritta e' rinviata a data da destinarsi. Le domande di partecipazione gia' "
        "presentate restano valide; le nuove date saranno rese note con pubblicazione"
        + GU
        + " almeno 20 giorni prima.",
    ],
)
def test_proroghe_e_rinvii_non_danno_una_data_sicura(testo):
    sc = ricava_scadenza(testo, date(2026, 10, 13))
    assert sc.data is None or sc.incerta or sc.data == date(2026, 11, 30)


def test_formula_e_data_scritta_che_divergono_sono_segnalate():
    testo = (
        "Le domande di partecipazione vanno presentate entro 30 giorni dalla pubblicazione"
        + GU
        + " Il termine di presentazione scade il 20 novembre 2026."
    )
    sc = ricava_scadenza(testo, date(2026, 10, 13))
    assert sc.incerta
    assert "2026-11-20" in sc.dettaglio
