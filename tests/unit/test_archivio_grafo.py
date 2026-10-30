"""Graph of the acts: extraction from the GU text and history queries. No network."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from gazzetta_mcp.archivio.grafo import (
    archi_citazioni,
    archi_correzione,
    estrai_archi_atto,
    estrai_archi_testo,
    salva_archi_atti,
    storico,
    urn_da_citazione,
    urn_proprio,
)
from gazzetta_mcp.archivio.store import ArchiveStore
from gazzetta_mcp.archivio.tipi import Arco
from gazzetta_mcp.models import Atto, Serie

FIX = Path(__file__).parent.parent / "fixtures"
URN_241 = "urn:nir:stato:legge:1990-08-07;241"
URN_50 = "urn:nir:stato:decreto.legislativo:2016-04-18;50"
URN_DPR150 = "urn:nir:stato:decreto.del.presidente.della.repubblica:2026-09-12;150"


def grafo_text(name: str) -> str:
    return (FIX / "grafo" / name).read_text(encoding="utf-8")


def atto(codice: str, titolo: str = "", testo: str = "") -> Atto:
    return Atto(
        codice=codice,
        serie=Serie.SG,
        data=date(2026, 10, 3),
        titolo=titolo,
        emettitore="X",
        tipo=None,
        testo=testo,
        link=f"https://example.test/{codice}",
    )


# -- extraction ---------------------------------------------------------------------------


def test_urn_from_citation_uses_normattiva_rules():
    assert urn_da_citazione("legge 7 agosto 1990, n. 241") == URN_241
    assert urn_da_citazione("legge 30 febbraio 1990, n. 241") is None  # impossible date


def test_errata_corrige_points_to_the_corrected_act():
    testo = grafo_text("errata_corrige.txt")
    assert archi_correzione("26A09999", "", testo) == [
        Arco("26A09999", URN_DPR150, "errata_corrige", "gu")
    ]


def test_errata_corrige_does_not_cite_its_own_target_twice():
    archi = estrai_archi_testo("26A09999", "", grafo_text("errata_corrige.txt"))
    assert [(a.a, a.tipo) for a in archi] == [(URN_DPR150, "errata_corrige"), (URN_241, "cita")]


def test_rettifica_with_title_formula():
    archi = archi_correzione(
        "26A1",
        "Rettifica relativa al decreto-legge 144/2026",
        "Nel testo, dove e' scritto «A» leggasi «B».",
    )
    assert archi == [Arco("26A1", "urn:nir:stato:decreto.legge:2026;144", "rettifica", "gu")]


def test_generic_comunicato_with_correction_cue_is_errata():
    testo = (
        "Comunicato relativo alla legge 7 agosto 1990, n. 241, pubblicata nella Gazzetta "
        "Ufficiale n. 192. All'art. 2 dove e' scritto: «x» leggasi: «y»."
    )
    assert archi_correzione("c", "", testo) == [Arco("c", URN_241, "errata_corrige", "gu")]


def test_false_positive_plain_comunicato_is_not_a_correction():
    testo = grafo_text("comunicato_semplice.txt")
    assert archi_correzione("c", "", testo) == []
    # the cited decree is still a plain citation
    assert [a.tipo for a in estrai_archi_testo("c", "", testo)] == ["cita"]


def test_false_positive_correction_without_complete_target():
    assert archi_correzione("c", "", grafo_text("rettifica_senza_numero.txt")) == []


def test_false_positive_rettifica_far_from_the_top_or_not_a_formula():
    # the word appears, but not as a formula directly followed by the act
    testo = (
        "Disposizioni sulla rettifica dei confini. " + "x " * 300 + "legge 7 agosto 1990, n. 241"
    )
    assert archi_correzione("c", "", testo) == []
    late = "premessa " * 80 + "Errata corrige alla legge 7 agosto 1990, n. 241"
    assert archi_correzione("c", "", late) == []


def test_correction_of_itself_is_ignored():
    titolo = "LEGGE 7 agosto 1990, n. 241 - Rettifica alla legge 7 agosto 1990, n. 241"
    assert archi_correzione("c", titolo, "") == []


def test_citations_from_a_real_gu_text():
    html = (FIX / "real" / "atto_testo_26A05182_sg.html").read_bytes()
    from gazzetta_mcp.parsing import extract_pre

    archi = archi_citazioni("26A05182", extract_pre(html))
    urns = {a.a for a in archi}
    assert "urn:nir:stato:decreto.legislativo:2001-03-30;165" in urns
    assert "urn:nir:stato:decreto.legislativo:2021-02-02;18" in urns
    assert all(a.tipo == "cita" and a.fonte == "gu" and a.da == "26A05182" for a in archi)
    assert len(urns) == len(archi)  # unique


def test_citations_shapes_and_false_positives():
    testo = grafo_text("legge_con_citazioni.txt")
    archi = estrai_archi_testo("26G1", "LEGGE 5 agosto 2026, n. 140 - Disposizioni", testo)
    urns = [a.a for a in archi]
    assert urns == [
        URN_241,
        URN_50,
        "urn:nir:stato:decreto.legge:2026;144",
        "urn:nir:stato:decreto.legislativo:2001;165",
        "urn:nir:stato:decreto.legislativo:2013-03-14;33",
    ]
    # not extracted: itself, regional law, EU regulation, "n. 241 del 1990", impossible date


def test_own_urn_from_title_only_when_title_starts_with_it():
    assert urn_proprio("LEGGE 7 agosto 1990, n. 241 - Nuove norme") == URN_241
    assert urn_proprio("DECRETO 9 settembre 2026 - Aggiornamento") is None
    assert urn_proprio("Aggiornamento ai sensi della legge 7 agosto 1990, n. 241") is None


def test_citations_are_capped_and_never_invented():
    testo = " ".join(f"legge 7 agosto 1990, n. {n}" for n in range(1, 400))
    assert len(archi_citazioni("c", testo)) == 100
    assert archi_citazioni("c", "nessun riferimento, solo la legge e il decreto") == []


def test_estrai_archi_atto_uses_title_and_text():
    a = atto("26A1", "ERRATA CORRIGE", "Errata corrige al decreto-legge 144/2026, art. 2.")
    assert [(x.tipo, x.a) for x in estrai_archi_atto(a)] == [
        ("errata_corrige", "urn:nir:stato:decreto.legge:2026;144")
    ]


# -- storing ------------------------------------------------------------------------------


@pytest.fixture
def store():
    with ArchiveStore(":memory:") as s:
        yield s


def test_salva_archi_atti_is_idempotent_and_records_own_urn(store):
    a = atto(
        "26G1",
        "LEGGE 5 agosto 2026, n. 140 - Disposizioni",
        "Visto la legge 7 agosto 1990, n. 241.",
    )
    store.put_atto(a, fonte="gu")
    assert salva_archi_atti(store, [a]) == 1
    assert salva_archi_atti(store, [a]) == 0
    assert store.archi_di("26G1") == [Arco("26G1", URN_241, "cita", "gu")]
    assert store.codice_da_urn("urn:nir:stato:legge:2026-08-05;140") == "26G1"


def test_own_urn_not_stolen_from_another_act(store):
    a = atto("26G1", "LEGGE 5 agosto 2026, n. 140 - X")
    b = atto("26G2", "LEGGE 5 agosto 2026, n. 140 - copia")
    store.put_atto(a, fonte="gu")
    store.put_atto(b, fonte="gu")
    salva_archi_atti(store, [a, b])
    assert store.codice_da_urn("urn:nir:stato:legge:2026-08-05;140") == "26G1"


# -- history ------------------------------------------------------------------------------


def archi(store, *triple):
    store.put_archi(Arco(da, a, tipo, "normattiva") for da, a, tipo in triple)


def test_storico_chain_both_directions(store):
    archi(
        store,
        ("B", "A", "modifica"),
        ("C", "B", "abroga"),
        ("E", "C", "rettifica"),
        ("A", "Z", "modifica"),
        ("Z", "Y", "modifica"),
        ("A", "Q", "cita"),  # citations are not history
        ("W", "A", "attua"),
    )
    v = storico(store, "A")
    assert [(x.codice, x.profondita, x.direzione) for x in v] == [
        ("B", 1, "agisce_su"),
        ("Z", 1, "subisce"),
        ("C", 2, "agisce_su"),
        ("Y", 2, "subisce"),
        ("E", 3, "agisce_su"),
    ]
    assert {x.codice: x.tipo for x in v}["C"] == "abroga"


def test_storico_depth_cap(store):
    archi(store, ("B", "A", "modifica"), ("C", "B", "modifica"), ("D", "C", "modifica"))
    assert [x.codice for x in storico(store, "A", profondita=2)] == ["B", "C"]
    assert [x.codice for x in storico(store, "A", profondita=1)] == ["B"]
    assert storico(store, "A", profondita=0) == []


def test_storico_survives_cycles_and_self_loops(store):
    archi(
        store,
        ("B", "A", "modifica"),
        ("A", "B", "modifica"),  # 2-cycle with A
        ("C", "B", "modifica"),
        ("B", "C", "abroga"),  # 2-cycle B/C
        ("A", "A", "modifica"),  # self loop
        ("D", "D", "modifica"),
    )
    v = storico(store, "A", profondita=20)
    assert {(x.codice, x.direzione) for x in v} == {
        ("B", "agisce_su"),
        ("C", "agisce_su"),
        ("B", "subisce"),
        ("C", "subisce"),
    }
    assert all(x.codice != "A" for x in v)


def test_storico_diamond_gives_shortest_chain_once(store):
    archi(
        store,
        ("B", "A", "modifica"),
        ("C", "A", "modifica"),
        ("D", "B", "modifica"),
        ("D", "C", "modifica"),
        ("D", "A", "abroga"),
    )
    d = [x for x in storico(store, "A") if x.codice == "D"]
    assert [(x.profondita, x.tipo) for x in d] == [(1, "abroga")]


def test_storico_resolves_urn_endpoints_to_archived_codes(store):
    a = atto("26G1", "LEGGE 7 agosto 1990, n. 241 - Nuove norme")
    store.put_atto(a, fonte="gu", urn=URN_241)
    store.put_archi([Arco("26A5", URN_241, "errata_corrige", "gu")])
    assert [(x.codice, x.tipo) for x in storico(store, "26G1")] == [("26A5", "errata_corrige")]
    assert [(x.codice, x.direzione) for x in storico(store, "26A5")] == [("26G1", "subisce")]
    # asking by URN works too
    assert [x.codice for x in storico(store, URN_241)] == ["26A5"]


def test_storico_unknown_act_is_empty(store):
    assert storico(store, "nope") == []
