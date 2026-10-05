"""Small helpers shared by the parsers."""

from __future__ import annotations

import re

_WS = re.compile(r"\s+")
_TRAILING_CODE = re.compile(r"\s*\(([A-Z0-9]{6,12})\)\s*$")
ELI_ID = re.compile(r"/eli/id/(\d{4})/(\d{2})/(\d{2})/([A-Za-z0-9]+)/([A-Za-z0-9]+)")
ELI_GU = re.compile(r"/eli/gu/(\d{4})/(\d{2})/(\d{2})/(\d+)/([A-Za-z0-9]+)")


class ParseError(ValueError):
    """The input is not the document we expected (empty, truncated, wrong format)."""


def decode(raw: bytes) -> str:
    """Decode a GU page: UTF-8 first, Windows-1252 as a fallback (never raises)."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def squash(text: str) -> str:
    """Collapse every run of whitespace (including NBSP) into one space and strip."""
    return _WS.sub(" ", text.replace("\xa0", " ")).strip()


def split_trailing_code(text: str) -> tuple[str, str | None]:
    """Split ``"some text. (26A05182)"`` into ``("some text.", "26A05182")``."""
    text = squash(text)
    m = _TRAILING_CODE.search(text)
    if not m:
        return text, None
    return text[: m.start()].rstrip(), m.group(1)


def https(url: str) -> str:
    """Normalise a link to https (the GU feeds still publish http links)."""
    url = url.strip()
    if url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return url


def eli_id(base_url: str, year: int, month: int, day: int, codice: str, serie: str) -> str:
    return f"{https(base_url).rstrip('/')}/eli/id/{year:04d}/{month:02d}/{day:02d}/{codice}/{serie}"
