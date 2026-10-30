from __future__ import annotations

import json
from datetime import date

from gazzetta_mcp.archivio import ArchiveStore
from gazzetta_mcp.archivio.__main__ import main
from gazzetta_mcp.models import Atto, Serie


def test_stato_reports_the_archive(tmp_path, monkeypatch, capsys):
    path = tmp_path / "archivio.sqlite3"
    monkeypatch.setenv("GAZZETTA_MCP_ARCHIVIO_PATH", str(path))
    with ArchiveStore(path) as store:
        store.put_atto(
            Atto("26A00001", Serie.SG, date(2026, 1, 5), "T", "E", None, "testo", "https://x"),
            fonte="gu",
        )
    assert main(["stato"]) == 0
    assert json.loads(capsys.readouterr().out)["atti"] == 1
