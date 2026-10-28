"""The tool novita_argomento. Logic in ``novita.py``; here only wiring and error mapping."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ..novita import novita_argomento as _novita
from .gazzetta import ServiceGetter, _guard


def register_novita(mcp: FastMCP, get_service: ServiceGetter) -> None:
    """Register novita_argomento on ``mcp``; ``get_service`` is called on every request."""

    @mcp.tool
    async def novita_argomento(
        argomento: str,
        serie: str | None = None,
        segna_come_letto: bool = True,
        limite: int = 20,
    ) -> dict[str, Any]:
        """Dice cosa e' uscito su un argomento dall'ultima volta che l'utente l'ha chiesto.

        Usalo per richieste come "cosa e' uscito su appalti dall'ultima volta", "ci sono novita'
        sul bonus edilizia", "aggiornami sui decreti sulla caccia". Basta l'argomento a parole
        (maiuscole, singolare e plurale sono equivalenti): il server ricorda in locale, sul
        computer dell'utente, fino a quale giorno ha gia' cercato quell'argomento. Al primo
        controllo non c'e' un'ultima volta: mostra gli ultimi 7 giorni e lo dice. Cerca come
        'cerca' (aggiorna con poche richieste distanziate i numeri recenti di SG e S4) nei
        titoli e negli enti, NON nel testo completo: la copertura puo' essere parziale e la
        risposta dichiara da quando a quando ha cercato; dillo all'utente. Gli atti sono dal
        piu' vecchio al piu' recente; se sono piu' di 'limite' quelli in piu' restano da
        vedere e vanno richiesti richiamando lo strumento.

        serie: facoltativa (SG, S1-S5, P2); un argomento su serie diverse e' ricordato a parte.
        segna_come_letto: con true (predefinito) il prossimo controllo parte da qui, ma solo fino
        a dove ha davvero cercato e mostrato; con false si guarda soltanto, senza cambiare nulla.
        limite: massimo di atti mostrati (fino a 100).
        """
        return await _guard(_novita(get_service(), argomento, serie, segna_come_letto, limite))


__all__ = ["register_novita"]
