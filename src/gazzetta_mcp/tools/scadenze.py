"""The tool scadenze_concorsi. Logic in ``scadenze_concorsi.py``; here only wiring."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ..scadenze_concorsi import scadenze_concorsi as _scadenze_concorsi
from .gazzetta import ServiceGetter, _guard


def register_scadenze(mcp: FastMCP, get_service: ServiceGetter) -> None:
    """Register scadenze_concorsi on ``mcp``; ``get_service`` is called on every request."""

    @mcp.tool
    async def scadenze_concorsi(
        parole_chiave: str | None = None,
        regione: str | None = None,
        entro_giorni: int = 7,
        limite: int = 10,
    ) -> dict[str, Any]:
        """Elenca i concorsi in scadenza nei prossimi giorni, con la data ricavata dal bando.

        Usalo per "quali concorsi scadono questa settimana", "concorsi per infermiere in
        Lombardia che scadono presto", "ultimi giorni per fare domanda". Parole chiave e
        regione sono facoltative. Parte dai bandi della 4a Serie Speciale degli ultimi 30
        giorni (come cerca_concorsi) e legge il testo di un numero LIMITATO di bandi (al massimo
        8 scaricamenti per chiamata, i testi gia' letti sono in cache e non contano): la
        risposta dichiara quanti bandi ha esaminato, quanti testi ha letto e quanti non
        indicano una scadenza. La data e' di norma 30 giorni dalla pubblicazione (con slittamento
        se cade in un giorno festivo) oppure una data scritta nel testo; il campo
        'scadenza_ricavata_da' dice quale. Dove la scadenza non si ricava non viene inventata:
        dillo all'utente e rimandalo al bando (link). Dai sempre per indicativa la data e
        invita a verificarla sul bando ufficiale. Se la risposta e' parziale ripeti la
        richiesta una volta sola, oppure restringi con parole chiave o regione.

        entro_giorni: scadenze comprese tra oggi e oggi + N giorni (0-60, predefinito 7).
        limite: massimo di risultati (fino a 50).
        """
        return await _guard(
            _scadenze_concorsi(get_service(), parole_chiave, regione, entro_giorni, limite)
        )


__all__ = ["register_scadenze"]
