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
    if message == "Errore interno imprevisto.":
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
        """Ultime pubblicazioni della Gazzetta Ufficiale (feed RSS ufficiale).

        serie: SG (Serie Generale), S1 (Corte Costituzionale), S2 (Unione Europea),
        S3 (Regioni), S4 (Concorsi ed esami), S5 (Contratti pubblici), P2 (Parte II).
        giorni: quanti giorni indietro includere (1-90). Il feed contiene solo i numeri recenti.
        """
        return await _guard(get_service().ultime_pubblicazioni(serie, giorni))

    @mcp.tool
    async def sommario(data: str, serie: str = "SG") -> dict[str, Any]:
        """Sommario di un numero della Gazzetta Ufficiale, con codice, titolo, emettitore,
        rubrica e link di ogni atto, piu' il link al numero e al PDF.

        data: giorno di pubblicazione, formato AAAA-MM-GG. serie: SG, S1-S5, P2.
        """
        return await _guard(get_service().sommario(data, serie))

    @mcp.tool
    async def leggi_atto(
        codice: str, data: str | None = None, serie: str | None = None, offset: int = 0
    ) -> dict[str, Any]:
        """Testo di un atto dal codice redazionale (es. 26A05182), ripulito per la lettura.

        data (AAAA-MM-GG) e serie servono per costruire il link ufficiale: se l'atto e' gia' in
        cache o nel feed la data si ricava da sola, altrimenti va indicata (la si trova con
        ultime_pubblicazioni, sommario o cerca). I testi lunghi sono divisi in pagine: usa
        offset con il valore 'prossimo_offset' del risultato precedente per continuare.
        """
        return await _guard(get_service().leggi_atto(codice, data, serie, offset))

    @mcp.tool
    async def cerca_concorsi(parole_chiave: str, regione: str | None = None) -> dict[str, Any]:
        """Cerca bandi di concorso (4a Serie Speciale) per parole chiave ed eventualmente regione.

        Copre SOLO la cache locale e l'ultimo feed S4: non esplora l'archivio della Gazzetta.
        """
        return await _guard(get_service().cerca_concorsi(parole_chiave, regione))

    @mcp.tool
    async def rimando_normattiva(atto: str) -> dict[str, Any]:
        """Costruisce il link permanente a Normattiva (testo vigente) per un atto.

        atto: estremi in testo libero, ad esempio 'legge 5 agosto 2026, n. 140',
        'DL 144/2026' o un codice redazionale GU. Solo link: nessun testo viene scaricato.
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
    ) -> dict[str, Any]:
        """Ricerca a testo pieno nella cache locale (atti, sommari e feed gia' consultati).

        Filtri facoltativi: serie (SG, S1-S5, P2), tipo (es. DECRETO, LEGGE, AVVISO),
        dal / al (AAAA-MM-GG), limite (massimo 100). Non interroga il sito della Gazzetta.
        """

        async def run() -> dict[str, Any]:
            return get_service().cerca(testo, serie, tipo, dal, al, limite)

        return await _guard(run())


__all__ = ["ServiceError", "register"]
