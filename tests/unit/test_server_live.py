"""Live smoke test against the real site (run with ``--live``). One feed request only."""

from __future__ import annotations

import pytest
from fastmcp import Client

from gazzetta_mcp.cache.sqlite import SqliteCache
from gazzetta_mcp.config import Settings
from gazzetta_mcp.server import create_server
from gazzetta_mcp.service import build_service


@pytest.mark.live
async def test_live_ultime_pubblicazioni(tmp_path):
    settings = Settings(cache_path=tmp_path / "cache.sqlite3")
    service = build_service(settings)
    assert isinstance(service._cache, SqliteCache)
    try:
        async with Client(create_server(service)) as client:
            result = await client.call_tool("ultime_pubblicazioni", {"serie": "SG", "giorni": 30})
        assert result.data["ultimo_numero"] > 0
        assert result.data["fonte"] and result.data["avvertenza"]
    finally:
        await service.aclose()
