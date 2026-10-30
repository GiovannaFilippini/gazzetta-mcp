"""Central archive of the Gazzetta Ufficiale and Normattiva (step 2, decision 090).

The store is the shared contract: ingestion, graph and client code only talk to ``ArchiveStore``.
"""

from .store import ArchiveError, ArchiveStore
from .tipi import ARCHI_TIPI, FONTI, Arco, NumeroDaFare

__all__ = ["ARCHI_TIPI", "FONTI", "ArchiveError", "ArchiveStore", "Arco", "NumeroDaFare"]
