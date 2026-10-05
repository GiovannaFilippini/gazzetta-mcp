from __future__ import annotations

import pytest

from gazzetta_mcp.regioni import (
    REGIONI,
    normalize,
    normalizza_regione,
    regione_da_testo,
    regione_ente,
)


def test_twenty_regions():
    assert len(REGIONI) == 20 and len(set(REGIONI)) == 20


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Città  di L'Aquila", "citta di l aquila"),
        ("UNIVERSITA' DI TRENTO", "universita di trento"),
        ("«CARLO BESTA»", "carlo besta"),
        ("Forlì-Cesena", "forli cesena"),
        ("", ""),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    ("ente", "expected"),
    [
        # region names
        ("AZIENDA REGIONALE DELLA SALUTE DELLA SARDEGNA DI SELARGIUS", "Sardegna"),
        ("Regione Siciliana - Assessorato della salute", "Sicilia"),
        ("AZIENDA SANITARIA UNIVERSITARIA FRIULI CENTRALE DI UDINE", "Friuli-Venezia Giulia"),
        ("Azienda USL della Valle d'Aosta", "Valle d'Aosta"),
        ("Provincia autonoma di Bolzano", "Trentino-Alto Adige"),
        ("Azienda sanitaria dell'Alto Adige", "Trentino-Alto Adige"),
        ("Politecnica delle Marche", "Marche"),
        ("AUSL Romagna", "Emilia-Romagna"),
        # towns and provinces
        ("AZIENDA SANITARIA LOCALE ROMA 5 - TIVOLI", "Lazio"),
        ("AZIENDA SANITARIA LOCALE ROMA 1 DI ROMA", "Lazio"),
        ("AZIENDA SANITARIA LOCALE DI MATERA", "Basilicata"),
        ("AZIENDA SANITARIA LOCALE NAPOLI 2 NORD - FRATTAMAGGIORE", "Campania"),
        ("AZIENDA SANITARIA LOCALE 02 DI LANCIANO - VASTO - CHIETI", "Abruzzo"),
        ("AZIENDA SOCIO-SANITARIA TERRITORIALE DI PAVIA", "Lombardia"),
        ("AZIENDA SOCIO-SANITARIA TERRITORIALE DEGLI SPEDALI CIVILI DI BRESCIA", "Lombardia"),
        ("UNIVERSITA' COMMERCIALE «LUIGI BOCCONI» DI MILANO", "Lombardia"),
        ("Università degli studi di Perugia", "Umbria"),
        ("Università degli studi di Padova", "Veneto"),
        ("UNIVERSITA' DI TRENTO", "Trentino-Alto Adige"),
        ("Comune di Bari", "Puglia"),
        ("Comune di Cagliari", "Sardegna"),
        ("Comune di Palermo", "Sicilia"),
        ("Comune di Catanzaro", "Calabria"),
        ("Comune di Campobasso", "Molise"),
        ("Comune di Genova", "Liguria"),
        ("Comune di Ancona", "Marche"),
        ("Comune di Aosta", "Valle d'Aosta"),
        ("Comune di Firenze", "Toscana"),
        ("Comune di Torino", "Piemonte"),
        ("Comune di Bologna", "Emilia-Romagna"),
        ("Comune di Trieste", "Friuli-Venezia Giulia"),
        ("Comune di L'Aquila", "Abruzzo"),
        ("Comune di Forlì", "Emilia-Romagna"),
        # healthcare entities
        ("ESTAR", "Toscana"),
        ("AZIENDA SANITARIA LOCALE TO4 DI CHIVASSO", "Piemonte"),
        ("ASL TO 3", "Piemonte"),
        ("ASST Rhodense", "Lombardia"),
        ("Azienda socio sanitaria territoriale Fatebenefratelli", "Lombardia"),
        ("Azienda ospedaliera universitaria Careggi", "Toscana"),
        ("Policlinico Umberto I", "Lazio"),
        ("Azienda ospedaliera dei Colli", "Campania"),
        ("IRCCS Istituto Giannina Gaslini", "Liguria"),
        ("ARNAS Garibaldi", "Sicilia"),
        ("ULSS 6 Euganea", "Veneto"),
        # word boundaries and ambiguity
        ("Comune di Romagnano", None),
        ("Romagna Acque", "Emilia-Romagna"),
        ("Comune di Reggio Emilia", "Emilia-Romagna"),
        ("Comune di Reggio nell'Emilia", "Emilia-Romagna"),
        ("Comune di Reggio Calabria", "Calabria"),
        ("Università Mediterranea di Reggio Calabria", "Calabria"),
        ("Comune di Reggio", None),
        ("Comune di Trentola Ducenta", None),
        ("Comune di Castelfranco Emilia", "Emilia-Romagna"),
        ("Comune di Castelfranco Veneto", "Veneto"),
        # unknown
        ("CAMERA DEI DEPUTATI", None),
        ("MINISTERO DELL'ECONOMIA E DELLE FINANZE", None),
        ("ASL", None),
        ("AUSL", None),
        ("ASP", None),
        ("Policlinico", None),
        ("", None),
    ],
)
def test_regione_da_testo(ente, expected):
    assert regione_da_testo(ente) == expected


def test_title_towns_need_a_preposition():
    # "latina" the adjective must not be read as the town of Latina
    assert regione_ente("MINISTERO", "Concorso per filologia greca e latina") is None
    assert regione_ente("MINISTERO", "Avviamento a selezione presso l'ufficio di Lecce") == "Puglia"
    assert regione_ente("MINISTERO", "Borsa da usufruirsi presso la sede di Milano") == "Lombardia"
    # the issuing body wins over the title
    assert (
        regione_ente("UNIVERSITA' CATTOLICA DI MILANO", "Facolta' Gemelli di Roma") == "Lombardia"
    )


def test_last_place_wins_on_a_tie():
    assert regione_da_testo("Azienda ospedaliera di Padova e Milano") == "Lombardia"


@pytest.mark.parametrize(
    ("user", "expected"),
    [
        ("lombardia", "Lombardia"),
        ("  LOMBARDIA ", "Lombardia"),
        ("Regione Lombardia", "Lombardia"),
        ("Emilia Romagna", "Emilia-Romagna"),
        ("emilia-romagna", "Emilia-Romagna"),
        ("friuli", "Friuli-Venezia Giulia"),
        ("Friuli Venezia Giulia", "Friuli-Venezia Giulia"),
        ("sicilia", "Sicilia"),
        ("Valle d'Aosta", "Valle d'Aosta"),
        ("val d'aosta", "Valle d'Aosta"),
        ("Trentino", "Trentino-Alto Adige"),
        ("Alto Adige", "Trentino-Alto Adige"),
        ("Sudtirol", "Trentino-Alto Adige"),
        ("Bolzano", "Trentino-Alto Adige"),
        ("Aosta", "Valle d'Aosta"),
        ("puglia", "Puglia"),
        ("  ", None),
        (None, None),
    ],
)
def test_normalizza_regione(user, expected):
    assert normalizza_regione(user) == expected


def test_every_region_is_accepted_by_its_own_name():
    for r in REGIONI:
        assert normalizza_regione(r) == r
        assert normalizza_regione(r.lower()) == r


def test_unknown_region_input_lists_the_valid_ones():
    with pytest.raises(ValueError, match="non riconosciuta.*Lombardia"):
        normalizza_regione("Groenlandia")
