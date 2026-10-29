"""Reads the current text of an article ("testo vigente") from Normattiva Open Data.

Turns the user's words ("legge 241 del 1990, art. 3-bis") into a Normattiva reference, asks
for that one article and pages the text like ``leggi_atto``. See decision 110.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import Any

from .interfaces import NormattivaLinker
from .models import DISCLAIMER
from .parsing._util import ParseError
from .parsing.vigente import NoActError, parse_articolo
from .service import ServiceError
from .sources.gu import GuError, GuHttpError
from .sources.normattiva_vigente import NormattivaVigenteClient, VigenteNotFoundError

ATTRIBUZIONE = "Normattiva Open Data (dati.normattiva.it), licenza CC BY 4.0"

_SUFFIXES = (
    "bis|ter|quater|quinquies|sexies|septies|octies|novies|decies|undecies|duodecies|"
    "terdecies|quaterdecies|quindecies|sexdecies|septdecies|octodecies|novodecies|vicies"
)
_ARTICOLO = re.compile(
    rf"(?<![a-z])(?:articolo|art)\b\.?\s*(\d{{1,4}})(?:\s*[-\s]?\s*({_SUFFIXES})\b)?", re.IGNORECASE
)
_LEADING_DI = re.compile(r"^\s*(?:(?:del|della|dello|dell'|di|dei|nel|nella)\s+)+", re.IGNORECASE)
_SEPARATORS = " ,;:-"
_NUM_DEL_ANNO = re.compile(r"(?<!\d)(\d+)\s+del\s+(?:anno\s+)?(\d{4})(?!\d)", re.IGNORECASE)

_ESEMPI = "'legge 241 del 1990', 'legge 241/1990 art. 3' o 'decreto legislativo 33/2013 art. 5-bis'"


def split_articolo(atto: str) -> tuple[str, str | None]:
    """Split ``"art. 3-bis della legge 241/1990"`` into the act words and the article id.

    The article id is the form used in Normattiva links (``"3bis"``); None if none was named.
    """
    atto = _NUM_DEL_ANNO.sub(r"\1/\2", atto)  # "legge 241 del 1990" -> "legge 241/1990"
    m = _ARTICOLO.search(atto)
    if not m:
        return atto, None
    articolo = m.group(1) + (m.group(2) or "").lower()
    resto = f"{atto[: m.start()]} {atto[m.end() :]}"
    resto = _LEADING_DI.sub("", resto.strip(_SEPARATORS)).strip(_SEPARATORS)
    return resto, articolo


def _label(articolo: str) -> str:
    m = re.fullmatch(r"(\d+)([a-z]*)", articolo)
    return f"{m.group(1)}-{m.group(2)}" if m and m.group(2) else articolo


class VigenteReader:
    """Implements ``testo_vigente``: one request per call, cached for a day."""

    def __init__(
        self,
        client: NormattivaVigenteClient,
        linker: NormattivaLinker,
        max_chars: int,
        normattiva_base_url: str,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._client = client
        self._linker = linker
        self._max_chars = max_chars
        self._base = normattiva_base_url.rstrip("/")
        self._today = today

    async def leggi(self, atto: str, offset: int = 0) -> dict[str, Any]:
        if offset < 0:
            raise ServiceError("L'offset non puo' essere negativo: usa 0 per partire dall'inizio.")
        parole, articolo = split_articolo(atto or "")
        link = self._linker.link_for(parole)  # ValueError carries the Italian help text
        if not link.urn:
            raise ServiceError(
                "Per leggere il testo aggiornato servono tipo, numero e anno dell'atto: "
                f"scrivi ad esempio {_ESEMPI}. Il solo codice della Gazzetta non basta."
            )
        urn = link.urn + (f"~art{articolo}" if articolo else "")
        try:
            raw = await self._client.get_articolo(urn)
            art = parse_articolo(raw)
        except (VigenteNotFoundError, NoActError):
            raise ServiceError(self._non_trovato(link.atto, articolo)) from None
        except GuHttpError:
            raise ServiceError(
                "Il sito Normattiva non risponde o ha dato un errore. Riprova tra qualche "
                "minuto; se continua, apri il link a Normattiva con rimando_normattiva."
            ) from None
        except (GuError, ParseError):
            raise ServiceError(
                "Non sono riuscito a leggere la risposta di Normattiva. Apri il link a "
                "Normattiva con rimando_normattiva per leggere il testo sul sito."
            ) from None

        total = len(art.testo)
        if offset > total:
            raise ServiceError(
                f"L'offset {offset} supera la lunghezza del testo ({total} caratteri): "
                "usa un valore piu' basso, oppure 0 per ripartire dall'inizio."
            )
        end = min(total, offset + self._max_chars)
        chunk = art.testo[offset:end]
        next_offset = end if end < total else None
        if next_offset is not None:
            chunk += (
                f"\n\n[... testo troncato: mostrati i caratteri {offset}-{end} di {total}. "
                f"Per continuare richiama testo_vigente con offset={end}. ...]"
            )
        permalink = f"{self._base}/uri-res/N2Ls?{urn}"
        note = [
            (
                "Testo vigente: comprende le modifiche gia' applicate. Le parti tra doppie "
                "parentesi (( )) sono state aggiunte o sostituite da leggi successive; le note "
                "'AGGIORNAMENTO' dicono da quale."
            ),
            (
                "Normattiva non e' una fonte ufficiale: fa fede solo il testo pubblicato "
                f"nella Gazzetta Ufficiale. Fonte: {ATTRIBUZIONE}."
            ),
        ]
        if articolo is None:
            note.insert(
                0,
                "Hai indicato solo l'atto: qui c'e' il primo articolo (con l'intestazione). "
                "Per un altro articolo richiama con il numero, ad esempio "
                f"'{link.atto}, art. 2'.",
            )
        if art.altre_versioni:
            note.append(
                f"Normattiva ha trovato {art.altre_versioni + 1} versioni dell'atto "
                "(per esempio una ripubblicazione): ti mostro la prima."
            )
        return {
            "atto": link.atto,
            "titolo": art.titolo,
            "oggetto": art.sottotitolo,
            "articolo": _label(articolo) if articolo else "1 (primo articolo)",
            "testo": chunk,
            "in_vigore_dal": art.in_vigore_dal.isoformat() if art.in_vigore_dal else None,
            "verificato_il": self._today().isoformat(),
            "caratteri_totali": total,
            "offset": offset,
            "prossimo_offset": next_offset,
            "troncato": next_offset is not None,
            "nota": " ".join(note),
            "link_normattiva": permalink,
            "attribuzione": ATTRIBUZIONE,
            "licenza": "https://creativecommons.org/licenses/by/4.0/",
            "modifiche": "Testo convertito dal formato originale in testo semplice.",
            "fonte": [permalink, "https://dati.normattiva.it"],
            "avvertenza": DISCLAIMER,
        }

    @staticmethod
    def _non_trovato(citazione: str, articolo: str | None) -> str:
        if articolo:
            return (
                f"Non ho trovato l'articolo {_label(articolo)} di '{citazione}' su Normattiva. "
                "Controlla il numero dell'articolo (quelli aggiunti si chiamano ad esempio "
                "'3-bis') oppure chiedi senza articolo per partire dal primo."
            )
        return (
            f"Non ho trovato '{citazione}' su Normattiva. Controlla tipo, numero e anno "
            f"(ad esempio {_ESEMPI}), oppure cerca l'atto con cerca e riprova."
        )
