"""Small value types of the archive. No dependencies on the rest of the package."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..models import Serie

FONTI = ("gu", "normattiva")  # where an act was taken from

# Typed relations between acts (decision 090). ``da`` acts on ``a``.
ARCHI_TIPI = ("modifica", "abroga", "rettifica", "errata_corrige", "cita", "attua")


@dataclass(frozen=True)
class Arco:
    da: str  # code of the act that acts on the other
    a: str  # code of the act that is acted upon
    tipo: str  # one of ARCHI_TIPI
    fonte: str  # one of FONTI: who told us about the relation


@dataclass(frozen=True)
class NumeroDaFare:
    """One issue (serie + day) of the Gazzetta waiting to be archived."""

    serie: Serie
    data: date
    numero: int | None  # None while the issue number is still unknown
    tentativi: int
