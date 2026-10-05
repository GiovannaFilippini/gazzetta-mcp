"""The six tools. Business logic lives in ``service.py``; here only wiring and error mapping."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ..service import GazzettaService, ServiceError, user_message

log = logging.getLogger("gazzetta_mcp")

ServiceGetter = Callable[[], GazzettaService]

_EXPECTED = (Exception,)


def _fail(exc: Exception) -> ToolError:
    """Map any exception to a short Italian ToolError (no tracebacks to the client)."""
    message = user_message(exc)
    if message.startswith("Errore interno imprevisto"):
        log.exception("Unexpected error in a tool", exc_info=exc)
    return ToolError(message)


async def _guard(call: Awaitable[dict[str, Any]]) -> dict[str, Any]:
    try:
        return await call
    except ToolError:
        raise
    except _EXPECTED as exc:
        raise _fail(exc) from None


def register(mcp: FastMCP, get_service: ServiceGetter) -> None:
    """Register the six tools on ``mcp``; ``get_service`` is called on every request."""

    @mcp.tool
    async def ultime_pubblicazioni(serie: str = "SG", giorni: int = 7) -> dict[str, Any]:
        """Elenca le ultime cose uscite in Gazzetta Ufficiale (feed ufficiale).

        Usalo quando l'utente chiede le novita': "cosa e' uscito oggi in Gazzetta", "ci sono
        nuovi decreti questa settimana", "ultimi concorsi pubblicati". Non servono date o
        codici. Ogni voce ha un codice (es. 26A05182) che poi basta passare a leggi_atto.
        Copertura parziale: il feed contiene solo i numeri piu' recenti; per giorni piu'
        lontani usa sommario o cerca.

        serie: SG (Serie Generale, la piu' comune), S1 (Corte Costituzionale), S2 (Unione
        Europea), S3 (Regioni), S4 (Concorsi ed esami), S5 (Contratti pubblici), P2 (Parte II).
        giorni: quanti giorni indietro includere (1-90).
        """
        return await _guard(get_service().ultime_pubblicazioni(serie, giorni))

    @mcp.tool
    async def sommario(data: str, serie: str = "SG") -> dict[str, Any]:
        """Elenco completo degli atti di un numero della Gazzetta Ufficiale di un certo giorno.

        Usalo quando l'utente indica un giorno: "cosa e' uscito il 2 ottobre", "sommario della
        Gazzetta del 15 settembre". Se l'utente non indica un giorno usa invece
        ultime_pubblicazioni. Restituisce codice, titolo, emettitore e link di ogni atto, piu'
        il link al numero e al PDF.

        data: giorno di pubblicazione, formato AAAA-MM-GG (converti tu le date dette a
        parole). serie: SG (predefinita), S1-S5, P2.
        """
        return await _guard(get_service().sommario(data, serie))

    @mcp.tool
    async def leggi_atto(
        codice: str, data: str | None = None, serie: str | None = None, offset: int = 0
    ) -> dict[str, Any]:
        """Legge il testo di un atto della Gazzetta Ufficiale, ripulito per la lettura.

        Usalo quando l'utente vuole il testo di un atto: "dammi il testo del decreto X",
        "riassumimi questo decreto", "cosa dice l'atto 26A05182". Il codice (es. 26A05182) lo
        trovi nei risultati di ultime_pubblicazioni, sommario, cerca o cerca_concorsi: non
        chiederlo all'utente. La data e la serie di solito NON servono: vengono ricordate dai
        risultati gia' visti o cercate tra le ultime pubblicazioni. Se l'atto non e' recente e
        non e' mai comparso in un risultato, cercalo prima con cerca o ultime_pubblicazioni.

        I testi lunghi sono divisi in pagine: per continuare richiama con offset uguale al
        'prossimo_offset' del risultato precedente. Il testo non e' ufficiale: cita sempre il
        link nel campo 'link'.
        """
        return await _guard(get_service().leggi_atto(codice, data, serie, offset))

    @mcp.tool
    async def cerca_concorsi(
        parole_chiave: str,
        regione: str | None = None,
        aperti: bool = True,
        includi_altri_atti: bool = False,
        limite: int = 30,
    ) -> dict[str, Any]:
        """Cerca bandi di concorso pubblico (4a Serie Speciale, Concorsi ed esami).

        Usalo per richieste come "concorsi per infermiere in Lombardia", "bandi per istruttore
        amministrativo", "ci sono concorsi per insegnanti in Toscana". Basta qualche parola
        chiave (profilo, ente, citta') e, se l'utente la nomina, la regione. Non chiedere date
        o codici. Al primo uso scarica, con poche richieste distanziate, i sommari dei numeri
        degli ultimi 30 giorni (tipicamente 8-9) e li tiene in cache. Cerca nel titolo e
        nell'ente di ogni atto, non nel testo del bando: ogni risposta dichiara i numeri
        esaminati, quindi i risultati possono essere parziali; dillo all'utente. La regione e'
        stimata dal nome dell'ente; gli atti di regione non determinata sono contati a parte.
        aperti: solo numeri degli ultimi 30 giorni (i bandi sono di norma ancora aperti);
        con false si aggiungono i numeri piu' vecchi gia' in cache.
        includi_altri_atti: aggiunge diari delle prove, graduatorie, rettifiche, commissioni.
        limite: massimo di risultati (fino a 100).
        Il bando completo va letto sul sito ufficiale (link in ogni risultato) o con leggi_atto.
        """
        return await _guard(
            get_service().cerca_concorsi(parole_chiave, regione, aperti, includi_altri_atti, limite)
        )

    @mcp.tool
    async def rimando_normattiva(atto: str) -> dict[str, Any]:
        """Costruisce il link a Normattiva (testo vigente) di una legge o di un decreto.

        Usalo per richieste come "link Normattiva della legge 241/1990", "dove leggo il testo
        aggiornato del DL 144/2026". Restituisce solo il link: nessun testo viene scaricato.

        atto: gli estremi in parole, ad esempio 'legge 5 agosto 2026, n. 140', 'DL 144/2026',
        'DPR 26 ottobre 1972 n. 633' oppure un codice di un atto gia' trovato.
        """

        async def run() -> dict[str, Any]:
            return get_service().rimando_normattiva(atto)

        return await _guard(run())

    @mcp.tool
    async def cerca(
        testo: str,
        serie: str | None = None,
        tipo: str | None = None,
        dal: str | None = None,
        al: str | None = None,
        limite: int = 20,
        aggiorna: bool = True,
        solo_vigenti: bool = True,
    ) -> dict[str, Any]:
        """Cerca per parole chiave tra gli atti della Gazzetta Ufficiale, anche a cache vuota.

        Usalo quando l'utente descrive un argomento senza codici: "decreti sul bonus
        edilizia", "atti che parlano di semplificazione", "qualcosa sulla caccia in Veneto".
        Mette i risultati in ordine di pertinenza; da un risultato prendi il codice per
        leggi_atto. Con aggiorna=true (predefinito) e serie SG, S4 o non indicata, scarica
        prima, con poche richieste distanziate, i sommari dei numeri recenti (SG: ultimi 24,
        circa 30 giorni; S4: ultimi 9) non ancora in cache. Si cerca nei titoli e negli enti
        (singolare e plurale sono equivalenti; se nessun titolo ha tutte le parole, ripiega su
        quelli che ne hanno almeno una), NON nel testo completo. In piu' interroga l'archivio
        degli atti normativi su Normattiva (leggi e decreti per titolo; senza dal copre l'ultimo
        anno; con solo_vigenti=true, predefinito, esclude gli atti gia' abrogati): quei
        risultati hanno origine 'normattiva' e per leggerli con leggi_atto va passata anche
        la data. La risposta dice quali date e quali archivi sono stati usati: la copertura
        puo' restare parziale (avvisi e concorsi vecchi non ci sono), dillo all'utente. Con
        aggiorna=false non si fa rete.

        Filtri facoltativi: serie (SG, S1-S5, P2), tipo (es. DECRETO, LEGGE, AVVISO),
        dal / al (AAAA-MM-GG), limite (massimo 100).
        """
        return await _guard(
            get_service().cerca(testo, serie, tipo, dal, al, limite, aggiorna, solo_vigenti)
        )


__all__ = ["ServiceError", "register"]
