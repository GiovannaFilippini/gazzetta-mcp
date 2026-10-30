"""The local service reads the archive after the cache and before the sources."""

from __future__ import annotations

from datetime import date

from gazzetta_mcp.archivio import ArchiveStore
from gazzetta_mcp.models import Atto, Serie

from ._service_helpers import make_service


def _archived(store: ArchiveStore) -> None:
    store.put_atto(
        Atto(
            codice="19A00001",
            serie=Serie.SG,
            data=date(2019, 3, 4),
            titolo="Decreto sulla pesca sportiva nei laghi",
            emettitore="Ministero",
            tipo="decreto",
            testo="Articolo 1. La pesca sportiva nei laghi e' regolata come segue.",
            link="https://example.test/19A00001",
        ),
        fonte="gu",
    )


async def test_leggi_atto_uses_the_archive_without_calling_the_sources():
    service, seen, cache, _ = make_service()
    store = ArchiveStore(":memory:")
    _archived(store)
    service._archivio_store = store
    result = await service.leggi_atto("19A00001")
    assert "pesca sportiva" in str(result)
    assert seen == []  # no request to the GU
    assert cache.get_atto("19A00001") is not None  # now also in the device cache


async def test_cerca_finds_archived_acts_even_with_an_empty_cache():
    service, seen, _, _ = make_service()
    store = ArchiveStore(":memory:")
    _archived(store)
    service._archivio_store = store
    result = await service.cerca("pesca laghi", aggiorna=False)
    assert [r["codice"] for r in result["risultati"]] == ["19A00001"]
    assert result["risultati"][0]["origine"] == "archivio"
    assert seen == []


async def test_without_archive_nothing_changes():
    service, _, _, _ = make_service()
    result = await service.cerca("pesca laghi", aggiorna=False)
    assert result["risultati"] == []
