"""novita_argomento: what is new on a topic since the last time the user asked (decision 120).

The search is the one of ``cerca`` (``GazzettaService.cerca``); this module only remembers, per
topic, the last publication day really covered, and shows what came after. The memory is a table
of the local SQLite cache: nothing leaves the user's computer.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

from .cache.sqlite import Controllo
from .models import Serie
from .regioni import normalize
from .searchtext import search_words, stem
from .service import _REFRESHABLE, GazzettaService, ServiceError, _parse_serie

PRIMI_GIORNI = 7  # first check: nothing remembered yet, look at the last week
MAX_LIMITE = 100


def chiave_argomento(argomento: str, serie: Serie | None) -> str:
    """Same key for "Appalti", "appalto" and "APPALTI!"; word order does not matter.

    Words are lowercased, without accents or stopwords, reduced to their stem and sorted. The
    series is part of the key: the same words on two series are two different topics.
    """
    parole = sorted({stem(w) for w in search_words(normalize(argomento))})
    if not parole:
        raise ServiceError("Indica l'argomento di cui vuoi le novita'.")
    return " ".join(parole) + "|" + (serie.value if serie else "")


def _copertura(
    caricati: list[dict[str, Any]], atteso: list[Serie], dal: date, note: list[str]
) -> tuple[date | None, date | None]:
    """First and last day really covered by the issues ``cerca`` loaded, or (None, None).

    With more series the covered period is the one every series reaches (the shortest), and if
    an expected series was not loaded at all the coverage is unknown: a check must never be
    marked as done for a series that was not looked at. The same holds for a series whose list
    of recent issues could not be read, and an issue that failed to load is a hole: the coverage
    stops the day before it, so that its acts are looked for again at the next check.
    """
    per_serie = {c["serie"]: c for c in caricati if c.get("al")}
    if not atteso or any(s.value not in per_serie for s in atteso):
        return None, None
    righe = [per_serie[s.value] for s in atteso]
    if not all(r.get("completo", True) for r in righe):
        return None, None
    fino = min(date.fromisoformat(r["al"]) for r in righe)
    buchi = sorted(
        date.fromisoformat(d) for r in righe for d in r.get("mancanti", []) if d >= dal.isoformat()
    )
    if buchi:
        note.append(
            "Non ho potuto caricare i numeri del "
            + ", ".join(d.isoformat() for d in buchi)
            + ": il controllo si ferma prima, cosi' al prossimo tentativo vengono cercati di nuovo."
        )
        fino = min(fino, buchi[0] - timedelta(days=1))
        if fino < dal:
            return None, None
    return max(date.fromisoformat(r["dal"]) for r in righe), fino


async def novita_argomento(
    service: GazzettaService,
    argomento: str,
    serie: str | None = None,
    segna_come_letto: bool = True,
    limite: int = 20,
) -> dict[str, Any]:
    if not (argomento or "").strip():
        raise ServiceError("Indica l'argomento di cui vuoi le novita'.")
    s = _parse_serie(serie)
    chiave = chiave_argomento(argomento, s)
    limite = max(1, min(int(limite), MAX_LIMITE))
    cache = service._cache
    oggi = service._today()
    note: list[str] = []

    prima = cache.get_controllo(chiave)
    if prima is None:
        dal = oggi - timedelta(days=PRIMI_GIORNI)
        visti: frozenset[str] = frozenset()
    else:
        dal = prima.coperto_fino
        visti = prima.codici
        if dal > oggi:
            note.append(
                f"L'ultimo controllo e' datato {dal.isoformat()}, dopo la data di oggi "
                f"({oggi.isoformat()}): l'orologio del computer e' cambiato? Non cambio nulla."
            )

    risposta = await service.cerca(
        argomento, serie, None, dal.isoformat(), None, MAX_LIMITE, True, True, None
    )
    note.extend(risposta.get("note", []))
    trovati: list[dict[str, Any]] = risposta.get("risultati", [])
    atteso = [s] if s in _REFRESHABLE else [] if s else list(_REFRESHABLE)
    inizio, fino = _copertura(risposta.get("numeri_caricati", []), atteso, dal, note)
    troncata = len(trovati) >= MAX_LIMITE  # the search stopped at its cap: more may exist

    nuovi = [
        h
        for h in trovati
        if (
            h["data"] > dal.isoformat()
            or (h["data"] == dal.isoformat() and h["codice"] not in visti)
        )
        and (fino is None or h["data"] <= fino.isoformat())
    ]
    # Oldest first: what is shown can be marked as read in order, the rest stays for next time.
    nuovi.sort(key=lambda h: (h["data"], h["codice"]))
    mostrati, restanti = nuovi[:limite], nuovi[limite:]
    if fino is not None and len(nuovi) < len([h for h in trovati if h["data"] > dal.isoformat()]):
        note.append(
            "Alcuni atti sono piu' recenti dei numeri esaminati e non sono mostrati ora: "
            "compariranno al prossimo controllo."
        )

    # How far the check can move. Never past what was really covered or really shown.
    nuovo: Controllo | None = None
    if not segna_come_letto:
        motivo = "Come richiesto non ho segnato niente come letto: il prossimo controllo ripartira' dallo stesso punto."
    elif fino is None:
        motivo = (
            "Non ho segnato niente come letto: non so fino a quale giorno ho davvero cercato "
            "(serie senza aggiornamento automatico, oppure numeri non caricati)."
        )
    elif troncata:
        motivo = (
            "Non ho segnato niente come letto: ci sono troppi risultati per essere sicuro di "
            "averli visti tutti. Restringi con la serie o parole piu' precise."
        )
    elif prima is not None and fino < prima.coperto_fino and not restanti:
        motivo = "Non ho segnato niente come letto: i numeri esaminati sono piu' vecchi dell'ultimo controllo."
    else:
        punto = mostrati[-1]["data"] if restanti else fino.isoformat()
        punto_data = date.fromisoformat(punto)
        codici = {h["codice"] for h in mostrati if h["data"] == punto}
        if not restanti:  # everything up to the covered day was looked at
            codici |= {h["codice"] for h in trovati if h["data"] == punto}
        if prima is not None and punto_data == prima.coperto_fino:
            codici |= set(visti)
        if prima is not None and punto_data < prima.coperto_fino:
            motivo = "Non ho segnato niente come letto: il punto raggiunto e' precedente all'ultimo controllo."
        else:
            nuovo = Controllo(
                chiave=chiave,
                argomento=argomento.strip(),
                serie=s.value if s else "",
                coperto_fino=punto_data,
                codici=frozenset(codici),
                controllato_il=service._now(),
            )
            motivo = ""

    periodo_al = fino.isoformat() if fino else None
    if inizio is not None and inizio > dal:
        note.append(
            f"I numeri esaminati partono dal {inizio.isoformat()}, dopo l'ultimo controllo "
            f"({dal.isoformat()}): gli atti dei giorni in mezzo potrebbero mancare."
        )
    if prima is None:
        intro = (
            f"E' la prima volta che chiedi di '{argomento.strip()}': mostro gli ultimi "
            f"{PRIMI_GIORNI} giorni (dal {dal.isoformat()})."
        )
    else:
        intro = (
            f"Novita' dopo l'ultimo controllo ({prima.coperto_fino.isoformat()}, chiesto il "
            f"{prima.controllato_il.date().isoformat()})."
        )
    copertura = (
        f"Cercato dal {dal.isoformat()} al "
        + (periodo_al or "giorno non determinato")
        + " nei titoli e negli enti degli atti dei numeri recenti (non nel testo completo). "
        "La copertura puo' essere parziale: il server vede solo i numeri recenti e cio' che ha "
        "gia' in cache."
    )

    out: dict[str, Any] = {
        "argomento": argomento.strip(),
        "serie": s.value if s else None,
        "primo_controllo": prima is None,
        "ultimo_controllo": prima.controllato_il.isoformat() if prima else None,
        "periodo_cercato": {"dal": dal.isoformat(), "al": periodo_al},
        "copertura": intro + " " + copertura,
        "totale_novita": len(nuovi),
        "mostrate": len(mostrati),
        "non_mostrate": len(restanti),
        "risultati": [
            {k: h[k] for k in ("codice", "serie", "data", "titolo", "estratto", "link", "origine")}
            for h in mostrati
        ],
        "segnato_come_letto": False,
        "note": note,
    }
    if restanti:
        out["messaggio"] = (
            f"Ci sono altri {len(restanti)} atti piu' recenti: richiama lo strumento per vederli "
            "(sono mostrati dal piu' vecchio al piu' recente)."
        )
    elif not mostrati:
        out["messaggio"] = "Nessuna novita' sull'argomento nel periodo cercato."

    fonte = [h["link"] for h in mostrati[:5]]
    out = service._result(out, fonte or [service._base])
    # Only now, with the answer built, the check moves.
    if nuovo is not None:
        try:
            cache.put_controllo(nuovo)
            out["segnato_come_letto"] = True
            out["prossimo_controllo_da"] = nuovo.coperto_fino.isoformat()
        except sqlite3.Error:
            out["note"].append(
                "Non sono riuscito a salvare il punto del controllo: niente segnato."
            )
    elif motivo:
        out["note"].append(motivo)
    return out
