"""Client of the remote archive service (decision 090, step 2).

Speaks the MCP ``tools/call`` JSON-RPC over streamable HTTP with plain httpx: one request per
operation, short timeouts, no session. Everything that comes back is UNTRUSTED data: it is
validated field by field and truncated, and nothing in it is ever interpreted as an instruction.

The client never raises towards its caller for network or protocol problems: it returns an
empty result and bumps a counter, so the service falls back to the official sources. After a
429 (or a run of consecutive failures) it stops calling for a while (circuit breaker). The text
of a search is never logged.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from collections.abc import Callable
from datetime import date
from typing import Any
from urllib.parse import urlsplit

import httpx

from .. import __version__
from ..models import Atto, SearchFilters, SearchHit, Serie

log = logging.getLogger("gazzetta_mcp.cliente_remoto")

_CODICE = re.compile(r"^[0-9A-Z]{6,14}$")
ORIGINE = "archivio_remoto"

MAX_RISPOSTA = 2 * 1024 * 1024  # bytes read from one HTTP response
MAX_CHUNK = 200_000  # characters accepted in one piece of text
MAX_TESTO = 2_000_000  # characters of a whole act
MAX_RICHIESTE_LETTURA = 10  # requests spent to reassemble one act
MAX_RISULTATI = 50
MAX_TITOLO = 500
MAX_ESTRATTO = 1000
MAX_LINK = 500
MAX_CAMPO = 200

TIMEOUT_DEFAULT = 8.0
SOGLIA_ERRORI = 3  # consecutive failures that open the breaker
PAUSA_ERRORI = 60.0  # seconds of silence after them
PAUSA_429_DEFAULT = 60.0
PAUSA_MAX = 600.0

_RIFIUTO = object()  # the service answered, but with a tool error (e.g. act not found)


def url_ammesso(url: str) -> bool:
    """True for an https URL, or http only towards the local machine (tests, development)."""
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname
        _ = parts.port  # raises ValueError on a malformed port
    except ValueError:
        return False
    if not host or parts.username or parts.password:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and host in {"localhost", "127.0.0.1"}


def _str(valore: Any, massimo: int) -> str | None:
    return valore.strip()[:massimo] if isinstance(valore, str) else None


def _link(valore: Any) -> str | None:
    link = _str(valore, MAX_LINK)
    return link if link and link.startswith(("https://", "http://")) else None


def _data(valore: Any) -> date | None:
    try:
        return date.fromisoformat(valore) if isinstance(valore, str) else None
    except ValueError:
        return None


def _serie(valore: Any) -> Serie | None:
    try:
        return Serie(valore) if isinstance(valore, str) else None
    except ValueError:
        return None


def _intero(valore: Any) -> bool:
    return isinstance(valore, int) and not isinstance(valore, bool)


def _estrai(dati: bytes, tipo: str) -> Any:
    """The structured result of a tool; ``_RIFIUTO`` for a tool error; None if malformed."""
    try:
        testo = dati.decode("utf-8")
        messaggio: Any = None
        if "text/event-stream" in tipo:
            for riga in testo.splitlines():
                if riga.startswith("data:"):
                    candidato = json.loads(riga[5:])
                    if isinstance(candidato, dict) and (
                        "result" in candidato or "error" in candidato
                    ):
                        messaggio = candidato
                        break
        else:
            messaggio = json.loads(testo)
    except ValueError:  # includes UnicodeDecodeError
        return None
    if not isinstance(messaggio, dict):
        return None
    if "error" in messaggio:
        return _RIFIUTO
    res = messaggio.get("result")
    if not isinstance(res, dict):
        return None
    if res.get("isError"):
        return _RIFIUTO
    strutturato = res.get("structuredContent")
    if isinstance(strutturato, dict):
        return strutturato
    contenuto = res.get("content")
    if isinstance(contenuto, list) and contenuto and isinstance(contenuto[0], dict):
        try:
            valore = json.loads(contenuto[0].get("text", ""))
        except (ValueError, TypeError):
            return None
        return valore if isinstance(valore, dict) else None
    return None


class ClienteRemoto:
    def __init__(
        self,
        url: str,
        *,
        timeout: float = TIMEOUT_DEFAULT,
        user_agent: str = f"gazzetta-mcp/{__version__} (unofficial open source client)",
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not url_ammesso(url):
            raise ValueError("L'URL dell'archivio remoto deve iniziare con https://")
        self._url = url.strip()
        self._clock = clock
        self._fermo_fino = 0.0  # no calls before this instant (circuit breaker)
        self._errori_di_fila = 0
        self.contatori: Counter[str] = Counter()
        self._http = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            follow_redirects=False,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    @property
    def sospeso(self) -> bool:
        """True while the breaker is open: calls are skipped without touching the network."""
        return self._clock() < self._fermo_fino

    # --- transport ------------------------------------------------------------------

    def _fallimento(self, motivo: str, pausa: float | None = None) -> None:
        self.contatori[motivo] += 1
        self._errori_di_fila += 1
        if pausa is None and self._errori_di_fila >= SOGLIA_ERRORI:
            pausa = PAUSA_ERRORI
        if pausa is not None:
            pausa = min(pausa, PAUSA_MAX)
            self._fermo_fino = self._clock() + pausa
            self._errori_di_fila = 0
            log.info("archivio remoto sospeso per %.0f s (%s)", pausa, motivo)

    @staticmethod
    def _pausa_429(risposta: httpx.Response) -> float:
        try:
            return max(1.0, float(risposta.headers.get("retry-after", "")))
        except ValueError:
            return PAUSA_429_DEFAULT

    async def _chiama(self, strumento: str, argomenti: dict[str, Any]) -> dict[str, Any] | None:
        """One ``tools/call``; the tool's JSON result, or None for any kind of problem."""
        if self.sospeso:
            self.contatori["saltata"] += 1
            return None
        corpo = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": strumento, "arguments": argomenti},
        }
        dati = bytearray()
        try:
            async with self._http.stream("POST", self._url, json=corpo) as r:
                if r.status_code == 429:
                    self._fallimento("limitata", self._pausa_429(r))
                    return None
                if r.status_code != 200:
                    self._fallimento("errore_http")
                    return None
                async for pezzo in r.aiter_bytes():
                    dati += pezzo
                    if len(dati) > MAX_RISPOSTA:
                        self._fallimento("troppo_grande")
                        return None
                tipo = r.headers.get("content-type", "")
        except httpx.HTTPError:
            self._fallimento("rete")
            return None
        risultato = _estrai(bytes(dati), tipo)
        if risultato is None:
            self._fallimento("malformata")
            return None
        self._errori_di_fila = 0
        if risultato is _RIFIUTO:
            self.contatori["rifiutata"] += 1
            return None
        self.contatori["ok"] += 1
        return risultato

    # --- operations -----------------------------------------------------------------

    async def cerca(self, testo: str, filtri: SearchFilters) -> list[SearchHit]:
        limite = max(1, min(filtri.limite, MAX_RISULTATI))
        argomenti: dict[str, Any] = {"testo": testo.strip()[:200], "limite": limite}
        if filtri.serie is not None:
            argomenti["serie"] = filtri.serie.value
        if filtri.tipo:
            argomenti["tipo"] = filtri.tipo[:100]
        if filtri.dal:
            argomenti["dal"] = filtri.dal.isoformat()
        if filtri.al:
            argomenti["al"] = filtri.al.isoformat()
        risposta = await self._chiama("cerca_archivio", argomenti)
        if risposta is None:
            return []
        grezzi = risposta.get("risultati")
        if not isinstance(grezzi, list):
            self.contatori["malformata"] += 1
            return []
        hits: list[SearchHit] = []
        visti: set[str] = set()
        for g in grezzi[:limite]:
            if not isinstance(g, dict):
                continue
            codice = g.get("codice")
            serie, giorno = _serie(g.get("serie")), _data(g.get("data"))
            titolo, link = _str(g.get("titolo"), MAX_TITOLO), _link(g.get("link"))
            if (
                not isinstance(codice, str)
                or not _CODICE.match(codice)
                or codice in visti
                or serie is None
                or giorno is None
                or not titolo
                or link is None
            ):
                self.contatori["voce_scartata"] += 1
                continue
            visti.add(codice)
            hits.append(
                SearchHit(
                    codice=codice,
                    serie=serie,
                    data=giorno,
                    titolo=titolo,
                    estratto=_str(g.get("estratto"), MAX_ESTRATTO) or "",
                    link=link,
                    # The service sends them best first and gives no score: keep the order.
                    punteggio=max(0.0, 1.0 - 0.01 * len(hits)),
                    origine=ORIGINE,
                )
            )
        return hits

    async def leggi_atto(self, codice: str) -> Atto | None:
        """The act with its COMPLETE text, or None. Pieces are reassembled (bounded requests)."""
        if not _CODICE.match(codice):
            return None
        pezzi: list[str] = []
        offset = 0
        totale = 0
        prima: dict[str, Any] = {}
        for _ in range(MAX_RICHIESTE_LETTURA):
            r = await self._chiama("leggi_atto_archivio", {"codice": codice, "offset": offset})
            if r is None:
                return None
            testo, tot = r.get("testo"), r.get("caratteri_totali")
            prossimo = r.get("prossimo_offset")
            valido = (
                r.get("codice") == codice
                and isinstance(testo, str)
                and 0 < len(testo) <= MAX_CHUNK
                and _intero(tot)
                and 0 < tot <= MAX_TESTO
                and r.get("offset") == offset
                and (not prima or tot == totale)
                and (prossimo is None or (_intero(prossimo) and prossimo == offset + len(testo)))
            )
            if not valido:
                self.contatori["malformata"] += 1
                return None
            if not prima:
                prima, totale = r, tot
            pezzi.append(testo)
            offset += len(testo)
            if prossimo is None:
                break
        else:
            self.contatori["troppi_pezzi"] += 1
            return None
        completo = "".join(pezzi)
        if len(completo) != totale:  # a partial text must never pass for a whole one
            self.contatori["parziale"] += 1
            return None
        serie, giorno = _serie(prima.get("serie")), _data(prima.get("data"))
        titolo, link = _str(prima.get("titolo"), MAX_TITOLO), _link(prima.get("link"))
        if serie is None or giorno is None or not titolo or link is None:
            self.contatori["malformata"] += 1
            return None
        return Atto(
            codice=codice,
            serie=serie,
            data=giorno,
            titolo=titolo,
            emettitore=_str(prima.get("emettitore"), MAX_CAMPO) or "",
            tipo=None,
            testo=completo,
            link=link,
        )
