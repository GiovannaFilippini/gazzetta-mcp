"""Which calls close soon: candidates from the 4th series, deadline from the text of each call.

Takes the service as argument and reuses its recent issues and its reading of an act (both with
the existing rate limit and cache), plus its clock, limits and result envelope. At most
``MAX_LETTURE`` texts are downloaded per call: a text already in the cache costs nothing and
does not count. Nothing is invented: a call without a recognisable deadline is reported as such.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from .concorsi import BANDI, classify, estrai_posti, keyword_matcher
from .models import Serie
from .regioni import normalize, normalizza_regione, regione_ente
from .scadenze import METODO_NESSUNO, ricava_scadenza
from .service import GazzettaService, ServiceError

log = logging.getLogger("gazzetta_mcp")

MAX_LETTURE = 8  # texts downloaded per call (about 3 requests each, one per second)
MAX_GIORNI = 60  # largest "entro_giorni"
MAX_RISULTATI = 50
MAX_SENZA_SCADENZA = 10  # calls without a deadline listed by name (the rest only counted)
MAX_ERRORI_DI_FILA = 3  # stop reading when the site keeps failing
NON_RILEVATA = "scadenza non rilevata, controlla il bando"


def _priorita(data_gu: date, oggi: date, entro: int) -> tuple[int, date]:
    """Reading order: first the calls whose usual 30 days end inside the window, oldest first."""
    standard = data_gu + timedelta(days=30)
    in_finestra = oggi <= standard <= oggi + timedelta(days=entro)
    return (0 if in_finestra else 1, data_gu)


def _esito(sc, oggi: date, ultimo: date) -> str:
    """Where a call goes: "senza", "incerta_scaduta", "scaduta", "fuori" or "in_scadenza".

    A deadline that is uncertain (conflicting dates, e.g. an extension) and already past must not
    vanish among the expired calls: another date of the text may still be open.
    """
    if sc.metodo == METODO_NESSUNO or sc.data is None:
        return "senza"
    if sc.data < oggi:
        return "incerta_scaduta" if sc.incerta else "scaduta"
    return "fuori" if sc.data > ultimo else "in_scadenza"


async def scadenze_concorsi(
    service: GazzettaService,
    parole_chiave: str | None = None,
    regione: str | None = None,
    entro_giorni: int = 7,
    limite: int = 10,
) -> dict[str, Any]:
    if entro_giorni < 0:
        raise ServiceError("entro_giorni non puo' essere negativo: usa 0 per le scadenze di oggi.")
    entro_giorni = min(int(entro_giorni), MAX_GIORNI)
    limite = max(1, min(int(limite), MAX_RISULTATI))
    match = keyword_matcher(parole_chiave) if normalize(parole_chiave or "") else None
    reg = normalizza_regione(regione)  # ValueError (Italian) if not recognised

    recent = await service.ensure_recent_sommari(Serie.S4)
    oggi = service._today()
    taglio = oggi - timedelta(days=service._limits.concorsi_window_days)
    sommari = sorted((s for s in recent.sommari if s.data >= taglio), key=lambda s: s.data)

    # --- candidates: the calls of the window, filtered like cerca_concorsi ---------------
    candidati: list[dict[str, Any]] = []
    visti: set[str] = set()
    esaminati = regione_ignota = 0
    for som in sommari:
        for v in som.voci:
            if v.codice in visti:
                continue
            visti.add(v.codice)
            tipo = classify(v.titolo)
            if tipo not in BANDI:
                continue
            esaminati += 1
            if match is not None and not match(f"{v.titolo} {v.emettitore} {v.rubrica}"):
                continue
            area = regione_ente(v.emettitore, v.titolo)
            if reg is not None and area != reg:
                regione_ignota += area is None
                continue
            candidati.append(
                {
                    "codice": v.codice,
                    "ente": v.emettitore,
                    "oggetto": v.titolo,
                    "tipo": tipo,
                    "posti": estrai_posti(v.titolo),
                    "data_gu": som.data,
                    "numero_gu": som.numero,
                    "regione": area,
                    "link": v.link,
                }
            )
    candidati.sort(key=lambda c: _priorita(c["data_gu"], oggi, entro_giorni))

    # --- read the text of the first candidates, within the cap ----------------------------
    note = list(recent.notes)
    in_scadenza: list[dict[str, Any]] = []
    senza: list[dict[str, Any]] = []
    letti = scaduti = fuori = nuove_letture = errori = errori_di_fila = non_letti = 0
    ultimo = oggi + timedelta(days=entro_giorni)
    for i, c in enumerate(candidati):
        if nuove_letture >= MAX_LETTURE or errori_di_fila >= MAX_ERRORI_DI_FILA:
            non_letti = len(candidati) - i
            break
        try:
            atto = await service.leggi_atto(c["codice"], c["data_gu"].isoformat(), "S4")
        except Exception as exc:  # noqa: BLE001 - one failing text must not lose the others
            log.info("Text of %s not read: %s", c["codice"], exc)
            errori += 1
            errori_di_fila += 1
            senza.append(_senza(c, "testo del bando non letto per un errore: controlla il bando"))
            continue
        errori_di_fila = 0
        letti += 1
        nuove_letture += not atto.get("dalla_cache", False)
        sc = ricava_scadenza(atto.get("testo", ""), c["data_gu"])
        esito = _esito(sc, oggi, ultimo)
        if esito == "senza":
            senza.append(_senza(c, NON_RILEVATA))
        elif esito == "incerta_scaduta":
            senza.append(
                _senza(
                    c,
                    f"date contrastanti nel testo: la prima ({sc.data.isoformat()}) e' passata, "
                    "ma potrebbe esserci una proroga: controlla il bando",
                )
            )
        elif esito == "scaduta":
            scaduti += 1
        elif esito == "fuori":
            fuori += 1
        else:
            in_scadenza.append(_risultato(c, sc, oggi))
    in_scadenza.sort(key=lambda r: (r["scadenza"], r["data_gu"]))
    mostrati = in_scadenza[:limite]

    if non_letti:
        note.append(
            f"Letti {letti} testi su {len(candidati)} bandi candidati (tetto di {MAX_LETTURE} "
            f"scaricamenti per chiamata): {non_letti} bandi non sono stati controllati. Ripeti la "
            "richiesta per leggerne altri (quelli gia' letti non costano richieste), oppure "
            "restringi con parole chiave o regione."
        )
    if errori:
        note.append(
            f"{errori} testi non si sono potuti leggere: scadenza da controllare sul bando."
        )
    if len(in_scadenza) > len(mostrati):
        note.append(f"Mostrati {len(mostrati)} risultati su {len(in_scadenza)}: aumenta 'limite'.")
    if reg is not None and regione_ignota:
        note.append(
            f"Regione non determinata per {regione_ignota} bandi che corrispondono alle parole "
            "chiave: non sono mostrati. Ripeti la ricerca senza regione per vederli."
        )
    if not sommari:
        note.append("Nessun numero della 4a Serie Speciale disponibile: nessun bando esaminato.")
    if reg is not None and not candidati and sommari:
        note.append("Nessun bando della regione indicata tra quelli esaminati.")

    messaggio = None
    if not in_scadenza and (non_letti or senza or errori):
        messaggio = (
            "Non posso dire che nessun concorso scada nel periodo: "
            f"{non_letti} bandi non sono stati letti e {len(senza)} non hanno una scadenza "
            "sicura. Controlla anche i bandi elencati come 'senza scadenza rilevata' e il sito "
            "dell'ente."
        )
    elif not in_scadenza:
        messaggio = "Nessun concorso tra quelli esaminati scade nel periodo indicato."
    risultati = [{**r, "data_gu": r["data_gu"].isoformat()} for r in mostrati]
    senza_elenco = [{**s, "data_gu": s["data_gu"].isoformat()} for s in senza[:MAX_SENZA_SCADENZA]]
    if len(senza) > len(senza_elenco):
        note.append(
            f"{len(senza)} bandi senza scadenza rilevata: ne sono elencati {len(senza_elenco)}."
        )
    dal = sommari[0].data.isoformat() if sommari else None
    al = sommari[-1].data.isoformat() if sommari else None
    return service._result(
        {
            "parole_chiave": (parole_chiave or "").strip() or None,
            "regione": reg,
            "oggi": oggi.isoformat(),
            "entro_giorni": entro_giorni,
            "copertura": (
                f"Numeri della 4a Serie Speciale dal {dal} al {al} ({len(sommari)} numeri, "
                f"{esaminati} bandi esaminati, {len(candidati)} corrispondenti ai filtri). "
                f"Testi letti: {letti}, scadenza non rilevata o da controllare in {len(senza)}. "
                "Sono considerati solo i bandi usciti negli ultimi 30 giorni."
                if sommari
                else "Nessun numero della 4a Serie Speciale esaminato."
            ),
            "bandi_esaminati": esaminati,
            "bandi_candidati": len(candidati),
            "testi_letti": letti,
            "testi_non_letti": non_letti,
            "senza_scadenza": len(senza),
            "gia_scaduti": scaduti,
            "oltre_la_finestra": fuori,
            "richieste_effettuate": recent.richieste,
            "avviso_scadenza": (
                "Le date sono ricavate dal testo pubblicato in Gazzetta (di norma 30 giorni dalla "
                "pubblicazione, con slittamento dei giorni festivi): verifica sempre la scadenza "
                "sul bando ufficiale. Dove il testo non la indica non viene stimata."
            ),
            "note": note,
            "messaggio": messaggio,
            "totale": len(in_scadenza),
            "mostrati": len(mostrati),
            "risultati": risultati,
            "senza_scadenza_rilevata": senza_elenco,
        },
        [s.link for s in sommari[:3]] + [r["link"] for r in mostrati[:5]],
    )


def _risultato(c: dict[str, Any], sc, oggi: date) -> dict[str, Any]:
    out = {k: v for k, v in c.items()}
    out["scadenza"] = sc.data.isoformat()
    out["giorni_mancanti"] = (sc.data - oggi).days
    out["scadenza_ricavata_da"] = sc.metodo
    out["come"] = sc.dettaglio
    out["da_controllare"] = sc.incerta
    return out


def _senza(c: dict[str, Any], motivo: str) -> dict[str, Any]:
    return {
        "codice": c["codice"],
        "ente": c["ente"],
        "oggetto": c["oggetto"],
        "data_gu": c["data_gu"],
        "scadenza": None,
        "scadenza_ricavata_da": METODO_NESSUNO,
        "come": motivo,
        "link": c["link"],
    }
