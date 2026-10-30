"""Acquisition of normative acts from the Normattiva Open Data API into the archive.

Data: Normattiva Open Data (dati.normattiva.it), licence CC BY 4.0 (attribution required: the
source is recorded in ``normattiva.licenza``). Bulk download is allowed
there; this module still goes slowly (one rate limited request at a time) and stops at the first
sign of trouble. Shapes of the answers were checked on the real API on 2026-10-30 (decision 090):

* ``ricerca/avanzata`` lists acts by publication date, one page per request, metadata only
  (``codiceRedazionale``, ``dataGU``, ``numeroGU``, ``denominazioneAtto``, ``descrizioneAtto``,
  date and number of the act, ``titoloAtto``). ``numeroPagine`` tells how many pages there are.
* ``ricerca/aggiornati`` lists the acts changed in a period. Each one carries
  ``ultimiAttiModificanti``: the codes of the acts that changed it last (space separated). It is
  the only trace of the amendment relations in the open data and it only tells the *last* change,
  not the whole history; the kind of change (amends, repeals) is not given, so every relation is
  stored as ``modifica``.
* ``atto/dettaglio-atto-urn`` gives the text of ONE article. With ``@originale`` after the URN
  the wording as published. The whole act is not available in one request (decision 110), so
  the archived text is the title, the subject and the first article (preamble included).
  Such a text is PARTIAL: every act from here is stored with ``completo=False`` (never as a full
  text), and the Gazzetta Ufficiale acquisition later completes it (``sostituisci_atto``). If
  the API has no text for the act (400/404) only the metadata are kept, with the title/subject
  as text; an empty text is never stored as if it were a text.

An act is identified by the editorial code of the Gazzetta (``26G00185``), which Normattiva
gives for every act: the same act is thus recognised in both sources. Acts are immutable: one
that is already archived is never downloaded or overwritten again, its URN is just recorded.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol, TypeVar

import httpx

from ..config import Settings
from ..models import Atto, Serie
from ..parsing._util import ParseError
from ..parsing.vigente import parse_articolo
from ..sources.gu import GuError, GuHttpError
from ..sources.normattiva_vigente import NormattivaVigenteClient, VigenteNotFoundError
from ..sources.ratelimit import RateLimiter
from .store import ArchiveStore
from .tipi import Arco

FONTE = "normattiva"
CHIAVE_CURSORE = "normattiva.cursore"
CHIAVE_ERRORE = "normattiva.ultimo_errore"
PER_PAGINA = 40
PRIMO_GIORNO = date(1861, 1, 1)  # the oldest date the recovery goes back to by default
CHIAVE_SCARTATE = "normattiva.scartate"  # running count of entries dropped as invalid
CHIAVE_LICENZA = "normattiva.licenza"
LICENZA = "CC BY 4.0 - Normattiva Open Data (dati.normattiva.it)"
MAX_FINESTRE = 50  # default windows per recovery run
# Remote fields end up in a URN and in a link: accept only plain shapes.
_RE_TIPO = re.compile(r"[a-z]+(?:[ -][a-z]+){0,5}")
_RE_NUMERO = re.compile(r"[0-9]{1,6}(?:[-.]?[A-Za-z]{1,10})?")
_RE_CODICE = re.compile(r"[0-9A-Za-z]{4,16}")
BACKOFF_PREDEFINITO = (30.0, 120.0)  # waits before the 2nd and the 3rd attempt, then stop

Sleep = Callable[[float], Awaitable[None]]
_T = TypeVar("_T")


@dataclass(frozen=True)
class PaginaAtti:
    """One page of ``ricerca/avanzata``: the raw entries and the number of pages."""

    voci: list[dict[str, Any]]
    pagine: int
    scartate: int = 0  # entries the client could not even read (not objects)


class ClienteNormattiva(Protocol):
    """What the acquisition needs from the Normattiva Open Data API."""

    async def elenca_atti(self, dal: date, al: date, pagina: int) -> PaginaAtti: ...

    async def atti_aggiornati(self, dal: date, al: date) -> list[dict[str, Any]]: ...

    async def get_articolo(self, urn: str) -> bytes: ...


def _lista(data: dict) -> list:
    """``listaAtti`` of an answer. An empty window is valid only when the API says so
    (``numeroAttiTrovati`` 0, or an empty list) and gives no ``message``; anything else
    (null/missing list, error message) is a GuError: the caller must not treat it as empty."""
    if data.get("message"):
        raise GuError(f"Normattiva list: {str(data['message'])[:200]}")
    lista = data.get("listaAtti")
    if isinstance(lista, list):
        return lista
    if lista is None and str(data.get("numeroAttiTrovati")) == "0":
        return []
    raise GuError("Normattiva list: answer without listaAtti")


class NormattivaOpenData:
    """Real client: the two list endpoints plus the article client already in use elsewhere.

    Everything goes through one shared :class:`RateLimiter` and identifies itself with the
    user agent of the project. Any failure (network, 429, 5xx, bad answer) is a GuHttpError /
    GuError, never a silent retry.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._settings = settings or Settings()
        base = self._settings.normattiva_api_url.rstrip("/")
        self._url_avanzata = base + "/ricerca/avanzata"
        self._url_aggiornati = base + "/ricerca/aggiornati"
        self._limiter = limiter or RateLimiter(self._settings.requests_per_second)
        self._http = httpx.AsyncClient(
            transport=transport,
            timeout=self._settings.archivio_timeout_seconds,
            headers={"User-Agent": self._settings.user_agent, "Accept": "application/json"},
            follow_redirects=True,
        )
        self._articoli = NormattivaVigenteClient(
            self._settings, transport=transport, limiter=self._limiter
        )

    async def aclose(self) -> None:
        await self._http.aclose()
        await self._articoli.aclose()

    async def _post(self, url: str, body: dict) -> dict:
        await self._limiter.acquire()
        try:
            response = await self._http.post(
                url, content=json.dumps(body), headers={"Content-Type": "application/json"}
            )
        except httpx.HTTPError as exc:
            raise GuHttpError(f"Normattiva list failed: {exc!r}") from exc
        if response.status_code != 200:
            raise GuHttpError(f"Normattiva list: HTTP status {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise GuError("Normattiva list: unreadable answer") from exc
        if not isinstance(data, dict):
            raise GuError("Normattiva list: unexpected answer")
        return data

    async def elenca_atti(self, dal: date, al: date, pagina: int) -> PaginaAtti:
        body = {
            "orderType": "recente",
            "dataInizioPubProvvedimento": dal.isoformat(),
            "dataFinePubProvvedimento": al.isoformat(),
            "paginazione": {"paginaCorrente": pagina, "numeroElementiPerPagina": PER_PAGINA},
        }
        data = await self._post(self._url_avanzata, body)
        lista = _lista(data)
        voci = [v for v in lista if isinstance(v, dict)]
        try:
            pagine = int(data.get("numeroPagine") or 1)
        except (TypeError, ValueError) as exc:
            raise GuError("Normattiva list: bad page count") from exc
        return PaginaAtti(voci, pagine, len(lista) - len(voci))

    async def atti_aggiornati(self, dal: date, al: date) -> list[dict[str, Any]]:
        body = {
            "dataInizioAggiornamento": f"{dal.isoformat()}T00:00:00.000Z",
            "dataFineAggiornamento": f"{al.isoformat()}T23:59:59.999Z",
        }
        data = await self._post(self._url_aggiornati, body)
        return [v for v in _lista(data) if isinstance(v, dict)]

    async def get_articolo(self, urn: str) -> bytes:
        return await self._articoli.get_articolo(urn)


# -- reading the entries -------------------------------------------------------------------


def urn_da_voce(voce: dict[str, Any]) -> str | None:
    """``urn:nir:stato:<type>:<yyyy-mm-dd>;<number>`` of a list entry, None if incomplete."""
    tipo = str(voce.get("denominazioneAtto") or "").strip().lower()
    numero = str(voce.get("numeroProvvedimento") or voce.get("numeroAtto") or "").strip()
    if not _RE_TIPO.fullmatch(tipo) or not _RE_NUMERO.fullmatch(numero):
        return None
    try:
        giorno = date(
            int(voce["annoProvvedimento"]),
            int(voce["meseProvvedimento"]),
            int(voce["giornoProvvedimento"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if not tipo or not numero:
        return None
    tipo = ".".join(tipo.replace("-", " ").split())
    return f"urn:nir:stato:{tipo}:{giorno.isoformat()};{numero}"


def _codice(voce: dict[str, Any], urn: str) -> str:
    """The editorial code of the Gazzetta when Normattiva gives it, else the URN itself."""
    return str(voce.get("codiceRedazionale") or "").strip() or urn


def _codice_valido(voce: dict[str, Any]) -> bool:
    codice = str(voce.get("codiceRedazionale") or "").strip()
    return not codice or _RE_CODICE.fullmatch(codice) is not None


def atto_da_voce(voce: dict[str, Any], urn: str, testo: str, base_url: str) -> Atto | None:
    """Build the archive act from a list entry (partial text, see the module docstring).

    ``testo`` empty means "no text from the API": the title/subject is used as text.
    None if the publication date or any title is missing."""
    try:
        data = date.fromisoformat(str(voce["dataGU"]))
    except (KeyError, ValueError):
        return None
    descr = " ".join(str(voce.get("descrizioneAtto") or "").split())
    oggetto = " ".join(str(voce.get("titoloAtto") or "").strip("[] ").split())
    numero_gu = str(voce.get("numeroGU") or "")
    titolo = f"{descr}: {oggetto}" if descr and oggetto else (descr or oggetto)
    if not titolo:
        return None
    return Atto(
        codice=_codice(voce, urn),
        serie=Serie.SG,
        data=data,
        titolo=titolo,
        emettitore="",
        tipo=str(voce.get("denominazioneAtto") or "") or None,
        testo=testo or titolo,
        link=f"{base_url.rstrip('/')}/uri-res/N2Ls?{urn}",
        numero_gu=int(numero_gu) if numero_gu.isdigit() else None,
        scaricato_il=datetime.now(timezone.utc),
    )


def archi_da_normattiva(voci: Iterable[dict[str, Any]]) -> list[Arco]:
    """Amendment relations of the entries of ``ricerca/aggiornati``.

    ``ultimiAttiModificanti`` holds the codes of the acts that changed the entry last: one
    ``Arco(modifying, modified, "modifica", "normattiva")`` per code. Entries without codes
    (and relations of an act with itself) give nothing.
    """
    archi: list[Arco] = []
    for voce in voci:
        modificato = str(voce.get("codiceRedazionale") or "").strip()
        if not modificato:
            continue
        for modificante in str(voce.get("ultimiAttiModificanti") or "").split():
            if modificante != modificato:
                archi.append(Arco(modificante, modificato, "modifica", FONTE))
    return archi


# -- stopping and waiting ------------------------------------------------------------------


class _Sospeso(Exception):
    """The source is in trouble (429, 5xx, network): stop for now."""


async def _con_backoff(
    op: Callable[[], Awaitable[_T]], sleep: Sleep, backoff: tuple[float, ...]
) -> _T:
    """Run ``op``; on a transport/HTTP failure wait and retry as many times as ``backoff``
    says, then raise :class:`_Sospeso`. Other errors pass through."""
    for attesa in (*backoff, None):
        try:
            return await op()
        except GuHttpError as exc:
            if attesa is None:
                raise _Sospeso(str(exc)) from exc
            await sleep(attesa)
        except (VigenteNotFoundError, ParseError):
            raise
        except GuError as exc:  # unreadable answer, maintenance page: no point in retrying
            raise _Sospeso(str(exc)) from exc
    raise AssertionError("unreachable")  # pragma: no cover


async def _testo_atto(
    client: ClienteNormattiva, urn: str, sleep: Sleep, backoff: tuple[float, ...]
) -> str:
    """Title, subject and first article of the act as published. Empty if the API has no
    article for it (the caller then keeps only the title)."""
    try:
        raw = await _con_backoff(lambda: client.get_articolo(f"{urn}@originale"), sleep, backoff)
        articolo = parse_articolo(raw)
    except (VigenteNotFoundError, ParseError):
        return ""
    return "\n".join(p for p in (articolo.titolo, articolo.sottotitolo, articolo.testo) if p)


@dataclass
class _Corsa:
    """Progress of one run, kept outside the coroutines so a stop does not lose the count."""

    nuovi: int = 0
    scartate: int = 0
    completo: bool = False


# -- acquisition ---------------------------------------------------------------------------


async def _archivia_voce(
    client: ClienteNormattiva,
    store: ArchiveStore,
    voce: dict[str, Any],
    base_url: str,
    sleep: Sleep,
    backoff: tuple[float, ...],
) -> str:
    """Archive one entry; returns ``"nuovo"``, ``"presente"`` or ``"scartata"``.

    Nothing is downloaded for an act that is already there (from the GU or from an earlier
    run), only its URN is recorded. A new act is always stored as partial text
    (``completo=False``): the GU acquisition completes it later."""
    urn = urn_da_voce(voce) if _codice_valido(voce) else None
    if urn is None:
        return "scartata"
    codice = _codice(voce, urn)
    if store.has_atto(codice):
        store.set_urn(codice, urn)
        return "presente"
    testo = await _testo_atto(client, urn, sleep, backoff)
    atto = atto_da_voce(voce, urn, testo, base_url)
    if atto is None:
        return "scartata"
    return "nuovo" if store.put_atto(atto, fonte=FONTE, urn=urn, completo=False) else "presente"


async def _conta_voce(
    client: ClienteNormattiva,
    store: ArchiveStore,
    voce: dict[str, Any],
    base_url: str,
    sleep: Sleep,
    backoff: tuple[float, ...],
    corsa: _Corsa,
) -> None:
    esito = await _archivia_voce(client, store, voce, base_url, sleep, backoff)
    if esito == "nuovo":
        corsa.nuovi += 1
    elif esito == "scartata":
        corsa.scartate += 1


async def _acquisisci(
    client: ClienteNormattiva,
    store: ArchiveStore,
    dal: date,
    al: date,
    max_atti: int,
    base_url: str,
    sleep: Sleep,
    backoff: tuple[float, ...],
    corsa: _Corsa,
) -> None:
    """Fill ``corsa``. Raises _Sospeso when the source is in trouble."""
    pagina = 1
    while True:
        elenco = await _con_backoff(lambda p=pagina: client.elenca_atti(dal, al, p), sleep, backoff)
        for voce in elenco.voci:
            if corsa.nuovi >= max_atti:
                return
            await _conta_voce(client, store, voce, base_url, sleep, backoff, corsa)
        corsa.scartate += elenco.scartate
        if pagina >= elenco.pagine or not elenco.voci:
            corsa.completo = True
            return
        pagina += 1


def _esito(store: ArchiveStore, errore: str | None, corsa: _Corsa | None = None) -> None:
    """Record the outcome: the error (empty if clean), the dropped entries, the licence."""
    store.set_stato(CHIAVE_ERRORE, errore or "")
    store.set_stato(CHIAVE_LICENZA, LICENZA)
    if corsa is not None and corsa.scartate:
        prima = store.get_stato(CHIAVE_SCARTATE) or "0"
        totale = (int(prima) if prima.isdigit() else 0) + corsa.scartate
        store.set_stato(CHIAVE_SCARTATE, str(totale))


async def acquisisci_atti_normattiva(
    client: ClienteNormattiva,
    store: ArchiveStore,
    dal: date,
    al: date,
    *,
    max_atti: int,
    base_url: str | None = None,
    sleep: Sleep = asyncio.sleep,
    backoff: tuple[float, ...] = BACKOFF_PREDEFINITO,
) -> int:
    """Archive the acts published in the Gazzetta from ``dal`` to ``al`` (both included).

    Returns how many new acts were stored, at most ``max_atti``. Acts already archived are
    skipped without any download (their URN is recorded). On 429/5xx/network errors the
    request is retried after the waits in ``backoff`` and then the run stops, keeping what
    was done; the reason is saved in ``normattiva.ultimo_errore`` (empty after a clean run).
    An unreadable answer (not JSON, maintenance page, error message, list missing) stops the
    run at once. Entries with invalid fields are skipped and counted in ``normattiva.scartate``.
    New acts get the partial text only (``completo=False``). Data: CC BY 4.0, Normattiva Open
    Data (dati.normattiva.it).
    """
    corsa = _Corsa()
    base = base_url or Settings().normattiva_base_url
    try:
        await _acquisisci(client, store, dal, al, max_atti, base, sleep, backoff, corsa)
    except _Sospeso as exc:
        _esito(store, str(exc), corsa)
    else:
        _esito(store, None, corsa)
    return corsa.nuovi


async def acquisisci_archi_normattiva(
    client: ClienteNormattiva,
    store: ArchiveStore,
    dal: date,
    al: date,
    *,
    sleep: Sleep = asyncio.sleep,
    backoff: tuple[float, ...] = BACKOFF_PREDEFINITO,
) -> int:
    """Store the amendment relations of the acts changed from ``dal`` to ``al``.
    Returns how many relations were new (0 if the source is in trouble)."""
    try:
        voci = await _con_backoff(lambda: client.atti_aggiornati(dal, al), sleep, backoff)
    except _Sospeso as exc:
        _esito(store, str(exc))
        return 0
    return store.put_archi(archi_da_normattiva(voci))


async def aggiorna_normattiva(
    client: ClienteNormattiva,
    store: ArchiveStore,
    *,
    giorni: int = 7,
    max_atti: int = 500,
    oggi: Callable[[], date] = date.today,
    base_url: str | None = None,
    sleep: Sleep = asyncio.sleep,
    backoff: tuple[float, ...] = BACKOFF_PREDEFINITO,
) -> int:
    """Daily update: the acts published and the acts changed in the last ``giorni`` days.

    New acts are archived, the amendment relations of the changed ones are stored (and the
    changed acts not archived yet are archived too, within ``max_atti`` new acts in total).
    Returns how many new acts were stored.
    """
    al = oggi()
    dal = al - timedelta(days=giorni)
    base = base_url or Settings().normattiva_base_url
    corsa = _Corsa()
    try:
        await _acquisisci(client, store, dal, al, max_atti, base, sleep, backoff, corsa)
        voci = await _con_backoff(lambda: client.atti_aggiornati(dal, al), sleep, backoff)
        store.put_archi(archi_da_normattiva(voci))
        for voce in voci:
            if corsa.nuovi >= max_atti:
                break
            await _conta_voce(client, store, voce, base, sleep, backoff, corsa)
    except _Sospeso as exc:
        _esito(store, str(exc), corsa)
    else:
        _esito(store, None, corsa)
    return corsa.nuovi


async def recupera_normattiva(
    client: ClienteNormattiva,
    store: ArchiveStore,
    *,
    max_atti: int,
    finestra_giorni: int = 7,
    fino_a: date = PRIMO_GIORNO,
    max_finestre: int = MAX_FINESTRE,
    oggi: Callable[[], date] = date.today,
    base_url: str | None = None,
    sleep: Sleep = asyncio.sleep,
    backoff: tuple[float, ...] = BACKOFF_PREDEFINITO,
) -> int:
    """Backward recovery, newest to oldest, resumable.

    The cursor ``normattiva.cursore`` (ISO date) is the oldest day already covered: the next
    window ends the day before it (the first run starts from today). A window moves the cursor
    only when it was read to the end, so after a stop or when ``max_atti`` is reached the same
    window is read again next time, and the acts already archived cost no download. Stops at
    ``fino_a``. ``max_finestre`` caps the windows read in one run (each costs at least one
    request, even when empty), so a run in the sparse early decades stays bounded; the next
    run resumes from the cursor. Returns how many new acts were stored. Data: CC BY 4.0,
    Normattiva Open Data (dati.normattiva.it).
    """
    base = base_url or Settings().normattiva_base_url
    salvato = store.get_stato(CHIAVE_CURSORE)
    cursore = date.fromisoformat(salvato) if salvato else oggi() + timedelta(days=1)
    corsa = _Corsa()
    finestre = 0
    try:
        while cursore > fino_a and corsa.nuovi < max_atti and finestre < max_finestre:
            finestre += 1
            al = cursore - timedelta(days=1)
            dal = max(al - timedelta(days=finestra_giorni - 1), fino_a)
            corsa.completo = False
            await _acquisisci(client, store, dal, al, max_atti, base, sleep, backoff, corsa)
            if not corsa.completo:
                break
            cursore = dal
            store.set_stato(CHIAVE_CURSORE, cursore.isoformat())
    except _Sospeso as exc:
        _esito(store, str(exc), corsa)
    else:
        _esito(store, None, corsa)
    return corsa.nuovi
