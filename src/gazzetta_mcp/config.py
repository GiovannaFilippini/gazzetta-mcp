"""All tunable values, read from GAZZETTA_MCP_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__


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


@dataclass(frozen=True)
class Settings:
    gu_base_url: str = "https://www.gazzettaufficiale.it"
    normattiva_base_url: str = "https://www.normattiva.it"
    normattiva_api_url: str = "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1/api/v1"
    # Archive search through the Normattiva Open Data API (on by default, 1 request per search).
    archivio_normattiva: bool = True
    # Search form of the GU site (off by default: terms of use still to be confirmed with IPZS).
    ricerca_gu: bool = False
    requests_per_second: float = 1.0
    timeout_seconds: float = 20.0
    cache_path: Path = field(default_factory=_default_cache_path)
    cache_ttl_feed_seconds: int = 900
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
            requests_per_second=float(env("GAZZETTA_MCP_RPS", d.requests_per_second)),
            timeout_seconds=float(env("GAZZETTA_MCP_TIMEOUT", d.timeout_seconds)),
            cache_path=Path(env("GAZZETTA_MCP_CACHE_PATH", str(d.cache_path))),
            cache_ttl_feed_seconds=int(env("GAZZETTA_MCP_FEED_TTL", d.cache_ttl_feed_seconds)),
            user_agent=env("GAZZETTA_MCP_USER_AGENT", d.user_agent),
        )
