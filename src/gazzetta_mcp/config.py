"""All tunable values, read from GAZZETTA_MCP_* environment variables."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__

_log = logging.getLogger("gazzetta_mcp.config")


def _default_cache_path() -> Path:
    base = (
        os.environ.get("LOCALAPPDATA")
        or os.environ.get("XDG_CACHE_HOME")
        or str(Path.home() / ".cache")
    )
    return Path(base) / "gazzetta-mcp" / "cache.sqlite3"


def _flag(raw: str | None, default: bool) -> bool:
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "si", "on"}


def _url_remota(raw: str | None) -> str:
    """The remote archive URL, or "" (feature off) when unset or not allowed."""
    from .archivio.cliente_remoto import url_ammesso

    url = (raw or "").strip()
    if url and url_ammesso(url):
        return url
    if url:
        try:
            host = urlsplit(url).hostname or "?"
        except ValueError:
            host = "?"
        _log.warning(
            "GAZZETTA_MCP_ARCHIVIO_URL ignored (host %s): it must be an https URL "
            "without credentials; the remote archive stays off.",
            host,
        )
    return ""


def _secondi(raw: str | None, default: float) -> float:
    try:
        value = float(raw) if raw and raw.strip() else default
    except ValueError:
        return default
    return value if 0 < value <= 60 else default


@dataclass(frozen=True)
class Settings:
    gu_base_url: str = "https://www.gazzettaufficiale.it"
    normattiva_base_url: str = "https://www.normattiva.it"
    normattiva_api_url: str = "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1/api/v1"
    # Archive search through the Normattiva Open Data API (on by default, 1 request per search).
    archivio_normattiva: bool = True
    # Search form of the GU site (off by default: terms of use still to be confirmed with IPZS).
    ricerca_gu: bool = False
    # The Normattiva search is slow with date filters (tens of seconds): longer timeout.
    archivio_timeout_seconds: float = 90.0
    # Default period searched in the archives when the caller gives no dal.
    archivio_giorni: int = 365
    requests_per_second: float = 1.0
    timeout_seconds: float = 20.0
    cache_path: Path = field(default_factory=_default_cache_path)
    cache_ttl_feed_seconds: int = 900
    # Central archive (step 2, decision 090): its own SQLite file, separate from the cache.
    archivio_path: Path = field(
        default_factory=lambda: _default_cache_path().with_name("archivio.sqlite3")
    )
    # Remote archive service (decision 090): empty means off. Only https:// is accepted (plain
    # http only towards localhost); anything else is ignored.
    archivio_remoto_url: str = ""
    archivio_remoto_timeout: float = 8.0
    user_agent: str = f"gazzetta-mcp/{__version__} (unofficial open source client)"

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ.get
        d = cls()
        return cls(
            gu_base_url=env("GAZZETTA_MCP_GU_BASE_URL", d.gu_base_url).rstrip("/"),
            normattiva_base_url=env(
                "GAZZETTA_MCP_NORMATTIVA_BASE_URL", d.normattiva_base_url
            ).rstrip("/"),
            normattiva_api_url=env("GAZZETTA_MCP_NORMATTIVA_API_URL", d.normattiva_api_url).rstrip(
                "/"
            ),
            archivio_normattiva=_flag(
                env("GAZZETTA_MCP_ARCHIVIO_NORMATTIVA"), d.archivio_normattiva
            ),
            ricerca_gu=_flag(env("GAZZETTA_MCP_RICERCA_GU"), d.ricerca_gu),
            archivio_timeout_seconds=float(
                env("GAZZETTA_MCP_ARCHIVIO_TIMEOUT", d.archivio_timeout_seconds)
            ),
            archivio_giorni=int(env("GAZZETTA_MCP_ARCHIVIO_GIORNI", d.archivio_giorni)),
            requests_per_second=float(env("GAZZETTA_MCP_RPS", d.requests_per_second)),
            timeout_seconds=float(env("GAZZETTA_MCP_TIMEOUT", d.timeout_seconds)),
            cache_path=Path(env("GAZZETTA_MCP_CACHE_PATH", str(d.cache_path))),
            archivio_path=Path(env("GAZZETTA_MCP_ARCHIVIO_PATH", str(d.archivio_path))),
            cache_ttl_feed_seconds=int(env("GAZZETTA_MCP_FEED_TTL", d.cache_ttl_feed_seconds)),
            archivio_remoto_url=_url_remota(env("GAZZETTA_MCP_ARCHIVIO_URL")),
            archivio_remoto_timeout=_secondi(
                env("GAZZETTA_MCP_ARCHIVIO_REMOTO_TIMEOUT"), d.archivio_remoto_timeout
            ),
            user_agent=env("GAZZETTA_MCP_USER_AGENT", d.user_agent),
        )
