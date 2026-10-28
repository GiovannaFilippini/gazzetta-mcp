"""The tool ``testo_vigente``. Business logic lives in ``vigente.py``; here only wiring."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ..service import GazzettaService, user_message
from ..sources.normattiva_vigente import NormattivaVigenteClient
from ..sources.ratelimit import RateLimiter
from ..vigente import VigenteReader

log = logging.getLogger("gazzetta_mcp")


def register_vigente(
    mcp: FastMCP,
    get_service: Callable[[], GazzettaService],
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Register ``testo_vigente``. ``transport`` is only for tests (no network)."""
    limiters: dict[float, RateLimiter] = {}

    @mcp.tool
    async def testo_vigente(atto: str, offset: int = 0) -> dict[str, Any]:
        """Legge il testo VIGENTE (con le modifiche gia' applicate) di un articolo di legge.

        Usalo quando l'utente vuole sapere cosa dice oggi una norma: "cosa dice l'articolo 3
        della legge 241 del 1990", "testo aggiornato dell'art. 5-bis del d.lgs. 33/2013".
        leggi_atto invece da' il testo ORIGINALE pubblicato in Gazzetta, senza le modifiche
        successive. Il testo viene da Normattiva Open Data (licenza CC BY 4.0), un articolo
        per volta (una sola richiesta): se l'utente nomina l'articolo, includilo in 'atto';
        senza articolo si legge il primo. Non e' possibile leggere in un colpo tutto l'atto:
        per l'atto intero dai il link con rimando_normattiva. Non chiedere date o codici
        all'utente. Le parti tra doppie parentesi (( )) sono state modificate da leggi
        successive. Il testo non e' ufficiale: cita il link e l'attribuzione del risultato.

        atto: tipo, numero e anno in parole, con l'articolo se serve, ad esempio
        'legge 241 del 1990 art. 3', 'DPR 26 ottobre 1972 n. 633 articolo 17-bis',
        'decreto legislativo 33/2013 art. 5'.
        offset: per continuare un testo lungo, il 'prossimo_offset' del risultato precedente.
        """
        service = get_service()
        settings = service._settings  # same settings and cache as the other tools
        limiter = limiters.setdefault(
            settings.requests_per_second, RateLimiter(settings.requests_per_second)
        )
        client = NormattivaVigenteClient(
            settings, cache=service._cache, transport=transport, limiter=limiter
        )
        reader = VigenteReader(
            client,
            service._linker,
            service._limits.max_chars,
            settings.normattiva_base_url,
        )
        try:
            return await reader.leggi(atto, offset)
        except ToolError:
            raise
        except Exception as exc:
            message = user_message(exc)
            if message.startswith("Errore interno imprevisto"):
                log.exception("Unexpected error in a tool", exc_info=exc)
            raise ToolError(message) from None
        finally:
            await client.aclose()
