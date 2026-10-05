"""Parsers: bytes in, models out. No network, no cache. Implements ``interfaces.Parser``."""

from __future__ import annotations

from datetime import date

from ..models import Atto, Feed, Serie, Sommario
from ._util import ParseError
from .atto import parse_atto
from .elenco import parse_elenco_30giorni
from .feed import parse_feed
from .sommario import parse_sommario
from .text import clean_text, extract_export, extract_pre
from .tipo import detect_tipo


class GuParser:
    """Parser for the gazzettaufficiale.it pages.

    ``raw_text=True`` disables the text cleaning and returns the <pre> text as is
    (see docs/decisioni/020-pulizia-testo.md).
    """

    def __init__(self, raw_text: bool = False) -> None:
        self.raw_text = raw_text

    def parse_feed(self, raw: bytes, serie: Serie) -> Feed:
        return parse_feed(raw, serie)

    def parse_sommario(
        self, raw: bytes, serie: Serie, data: date, numero: int, base_url: str
    ) -> Sommario:
        return parse_sommario(raw, serie, data, numero, base_url)

    def parse_elenco_30giorni(self, raw: bytes) -> list[tuple[date, int]]:
        return parse_elenco_30giorni(raw)

    def parse_atto(
        self, scheda: bytes, testo: bytes, codice: str, serie: Serie, data: date, base_url: str
    ) -> Atto:
        return parse_atto(scheda, testo, codice, serie, data, base_url, raw_text=self.raw_text)


__all__ = [
    "GuParser",
    "ParseError",
    "clean_text",
    "detect_tipo",
    "extract_export",
    "extract_pre",
    "parse_atto",
    "parse_elenco_30giorni",
    "parse_feed",
    "parse_sommario",
]
