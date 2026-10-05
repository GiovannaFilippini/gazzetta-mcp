"""FastMCP entry point: ``gazzetta-mcp`` runs the server on the stdio transport."""

from __future__ import annotations

import argparse
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP

from . import __version__
from .models import DISCLAIMER
from .service import GazzettaService, build_service
from .tools import register

NAME = "gazzetta-mcp"

INSTRUCTIONS = (
    "Server locale e NON ufficiale per consultare la Gazzetta Ufficiale italiana. "
    "Regole d'uso: usa gli strumenti solo su richiesta dell'utente, mai in cicli o per scaricare "
    "l'archivio; ogni richiesta e' limitata in frequenza e salvata in cache. Per leggere un atto "
    "serve il codice redazionale (es. 26A05182) e, se non e' gia' in cache, la data: ricavala con "
    "ultime_pubblicazioni, sommario o cerca. cerca e cerca_concorsi coprono solo cio' che e' "
    "gia' in cache. Cita sempre il link ufficiale ('fonte') e ricorda all'utente: " + DISCLAIMER
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
    parser.parse_args(argv)
    create_server().run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    sys.exit(main())
