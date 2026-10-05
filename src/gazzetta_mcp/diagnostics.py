"""Command line helpers for non-technical users: ``--prova`` (self-test) and ``--svuota-cache``.

Nothing here raises to the user: every failure becomes a plain Italian OK/KO line with advice.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import httpx

from .config import Settings

Printer = Callable[[str], None]

_MIN_PYTHON = (3, 10)


def _check_python() -> tuple[bool, str]:
    version = ".".join(str(n) for n in sys.version_info[:3])
    if sys.version_info[:2] >= _MIN_PYTHON:
        return True, f"Python {version}"
    return False, (
        f"Python {version} e' troppo vecchio. Installa Python 3.10 o piu' recente "
        "(https://www.python.org/downloads/) e riprova."
    )


def _check_fts5() -> tuple[bool, str]:
    try:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE _probe USING fts5(x)")
        finally:
            conn.close()
    except sqlite3.Error:
        return False, (
            "Questa installazione di Python non supporta la ricerca nel testo (FTS5). "
            "Installa una versione di Python da python.org, oppure usa 'uvx', che ne "
            "scarica una adatta."
        )
    return True, f"Ricerca nel testo disponibile (SQLite {sqlite3.sqlite_version})"


def _check_cache_path(path: Path) -> tuple[bool, str]:
    try:
        folder = path.expanduser().parent
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=folder):
            pass
    except OSError as exc:
        return False, (
            f"Non posso scrivere nella cartella della memoria locale ({path.parent}): "
            f"{exc.strerror or exc}. Scegline un'altra impostando la variabile "
            "GAZZETTA_MCP_CACHE_PATH (per esempio una cartella nella tua home)."
        )
    return True, f"Memoria locale (cache) scrivibile: {path}"


def _check_connectivity(
    settings: Settings, transport: httpx.BaseTransport | None
) -> tuple[bool, str]:
    """Exactly one request: the Serie Generale RSS feed."""
    url = f"{settings.gu_base_url.rstrip('/')}/rss/SG"
    try:
        with httpx.Client(
            timeout=settings.timeout_seconds,
            headers={"User-Agent": settings.user_agent},
            follow_redirects=True,
            transport=transport,
        ) as http:
            response = http.get(url)
    except httpx.HTTPError:
        return False, (
            "Non riesco a collegarmi al sito della Gazzetta Ufficiale. Controlla la "
            "connessione a Internet (e proxy o firewall aziendali) e riprova."
        )
    if response.status_code != 200:
        return False, (
            f"Il sito della Gazzetta Ufficiale ha risposto con un errore ({response.status_code}). "
            "Di solito e' temporaneo: riprova tra qualche minuto."
        )
    if b"<rss" not in response.content[:2000].lower() and b"<channel" not in response.content:
        return False, (
            "Il sito ha risposto ma con un contenuto inatteso (forse una pagina di "
            "manutenzione o un blocco di rete). Riprova piu' tardi."
        )
    return True, "Collegamento al sito della Gazzetta Ufficiale riuscito"


def prova(
    settings: Settings | None = None,
    *,
    out: Printer = print,
    transport: httpx.BaseTransport | None = None,
) -> int:
    """Run the self-test, print a short Italian report, return 0 when everything is OK."""
    settings = settings or Settings.from_env()
    out("gazzetta-mcp: controllo dell'installazione")
    checks: list[tuple[bool, str]] = [
        _check_python(),
        _check_fts5(),
        _check_cache_path(settings.cache_path),
        _check_connectivity(settings, transport),
    ]
    for ok, message in checks:
        out(f"  [OK] {message}" if ok else f"  [KO] {message}")
    if all(ok for ok, _ in checks):
        out("Tutto a posto: puoi usare gazzetta-mcp dal tuo assistente.")
        return 0
    out(
        "Alcuni controlli non sono riusciti: segui i consigli sopra e rilancia 'gazzetta-mcp --prova'."
    )
    return 1


def svuota_cache(
    settings: Settings | None = None, *, confermato: bool = False, out: Printer = print
) -> int:
    """Delete the local cache files. Requires ``confermato`` (the ``--si`` flag)."""
    settings = settings or Settings.from_env()
    path = settings.cache_path.expanduser()
    files = [p for p in (path, Path(f"{path}-wal"), Path(f"{path}-shm")) if p.exists()]
    if not files:
        out(f"La memoria locale e' gia' vuota (nessun file in {path}).")
        return 0
    if not confermato:
        out(f"Sto per cancellare la memoria locale (cache) in: {path}")
        out(
            "Nulla di ufficiale viene toccato: le informazioni verranno scaricate di nuovo quando servono."
        )
        out("Per confermare lancia: gazzetta-mcp --svuota-cache --si")
        return 1
    try:
        for p in files:
            p.unlink()
    except OSError as exc:
        out(
            f"Non sono riuscito a cancellare {path}: {exc.strerror or exc}. "
            "Chiudi l'assistente (o Claude Desktop) che sta usando gazzetta-mcp e riprova."
        )
        return 1
    out("Memoria locale cancellata. La prossima ricerca sara' un po' piu' lenta del solito.")
    return 0
