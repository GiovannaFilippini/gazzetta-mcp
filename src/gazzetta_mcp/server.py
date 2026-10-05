"""FastMCP entry point: ``gazzetta-mcp`` runs the server on the stdio transport."""

from __future__ import annotations

import argparse
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP

from . import __version__
from .diagnostics import prova, svuota_cache
from .models import DISCLAIMER
from .service import GazzettaService, build_service
from .tools import register

NAME = "gazzetta-mcp"

INSTRUCTIONS = (
    "Server locale e NON ufficiale per consultare la Gazzetta Ufficiale italiana. "
    "Chi ti scrive di solito non conosce codici ne' date: parti sempre dalle parole dell'utente. "
    "Se indica un argomento, un profilo o un concorso usa cerca_concorsi (concorsi) o cerca "
    "(tutto il resto); se chiede le novita' usa ultime_pubblicazioni; se indica un giorno usa "
    "sommario; per il link a una legge usa rimando_normattiva. Per leggere un atto usa "
    "leggi_atto con il codice (es. 26A05182) preso dai risultati precedenti: NON chiedere mai "
    "all'utente codici, date o serie, ricavali tu e converti le date dette a parole in AAAA-MM-GG. "
    "Spiega i risultati in italiano semplice, senza gergo. I risultati possono essere parziali "
    "(il server vede le pubblicazioni recenti e cio' che ha gia' consultato, non l'intero "
    "archivio): dillo con chiarezza, e se non trovi nulla suggerisci parole diverse o il sito "
    "ufficiale. Non fare cicli di molte chiamate e non scaricare l'archivio: poche richieste "
    "mirate, ognuna limitata in frequenza e salvata in cache. Se uno strumento da' un errore, "
    "leggi il consiglio nel messaggio e provane uno solo, altrimenti riferisci il problema. "
    "Cita sempre il link ufficiale ('fonte') e ricorda all'utente: " + DISCLAIMER
)


def create_server(service: GazzettaService | None = None) -> FastMCP:
    """Build the FastMCP app. With no ``service`` one is created (and closed) by the lifespan."""
    holder: dict[str, GazzettaService] = {}
    if service is not None:
        holder["service"] = service

    @asynccontextmanager
    async def lifespan(_app: FastMCP) -> AsyncIterator[dict[str, Any]]:
        owned = "service" not in holder
        if owned:
            holder["service"] = build_service()
        try:
            yield {}
        finally:
            if owned:
                await holder.pop("service").aclose()

    mcp = FastMCP(
        NAME,
        instructions=INSTRUCTIONS,
        version=__version__,
        lifespan=lifespan,
        mask_error_details=True,
    )

    def get_service() -> GazzettaService:
        return holder["service"]

    register(mcp, get_service)
    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog=NAME, description="Unofficial local MCP server for the Italian Gazzetta Ufficiale."
    )
    parser.add_argument("--version", action="version", version=f"{NAME} {__version__}")
    parser.add_argument(
        "--prova",
        action="store_true",
        help="controlla l'installazione (Python, ricerca, cartella della cache, collegamento)",
    )
    parser.add_argument(
        "--svuota-cache",
        action="store_true",
        help="cancella la memoria locale (cache); serve --si per confermare",
    )
    parser.add_argument("--si", action="store_true", help="conferma --svuota-cache")
    args = parser.parse_args(argv)
    if args.prova:
        sys.exit(prova())
    if args.svuota_cache:
        sys.exit(svuota_cache(confermato=args.si))
    if args.si:
        parser.error("--si si usa insieme a --svuota-cache")
    create_server().run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    sys.exit(main())
