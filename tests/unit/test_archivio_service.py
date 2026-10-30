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


async def test_partial_archived_text_is_not_served_as_the_full_act():
    service, _, _, _ = make_service()
    store = ArchiveStore(":memory:")
    store.put_atto(
        Atto("19A00002", Serie.SG, date(2019, 3, 4), "T", "E", None, "solo art. 1", "https://x"),
        fonte="normattiva",
        completo=False,
    )
    service._archivio_store = store
    assert service._archived_atto("19A00002") is None


async def test_a_broken_archive_never_stops_the_local_server():
    service, _, _, _ = make_service()
    store = ArchiveStore(":memory:")
    store.close()  # every later call raises a sqlite3 error
    service._archivio_store = store
    assert service._archived_atto("19A00001") is None
    result = await service.cerca("pesca laghi", aggiorna=False)
    assert result["risultati"] == []


def test_build_service_survives_a_corrupt_archive(tmp_path, monkeypatch):
    from gazzetta_mcp.config import Settings
    from gazzetta_mcp.service import build_service

    bad = tmp_path / "archivio.sqlite3"
    bad.write_text("non e' un database" * 100)
    settings = Settings(archivio_path=bad, cache_path=tmp_path / "cache.sqlite3")
    service = build_service(settings)
    assert service._archivio_store is None
