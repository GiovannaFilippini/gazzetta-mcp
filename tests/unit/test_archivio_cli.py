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


def test_stato_and_controlla_do_not_create_a_missing_archive(tmp_path, monkeypatch, capsys):
    path = tmp_path / "manca" / "archivio.sqlite3"
    monkeypatch.setenv("GAZZETTA_MCP_ARCHIVIO_PATH", str(path))
    assert main(["stato"]) == 0
    assert main(["controlla"]) == 1
    assert not path.exists()
    assert not path.parent.exists()


async def test_a_gu_problem_stops_all_gu_series_but_not_normattiva(tmp_path, monkeypatch):
    from gazzetta_mcp.archivio import __main__ as cli
    from gazzetta_mcp.config import Settings
    from gazzetta_mcp.sources.gu import GuHttpError

    chiamate: list[str] = []

    async def aggiorna_ko(client, parser, store, serie):
        chiamate.append(f"gu.{serie.value}")
        raise GuHttpError("429")

    async def normattiva_ok(client, store, **kwargs):
        chiamate.append("normattiva")
        return 3

    class FakeNormattiva:
        def __init__(self, settings):
            pass

        async def aclose(self):
            pass

    monkeypatch.setattr(cli, "aggiorna_recenti", aggiorna_ko)
    monkeypatch.setattr(cli, "aggiorna_normattiva", normattiva_ok)
    monkeypatch.setattr(cli, "NormattivaOpenData", FakeNormattiva)
    with ArchiveStore(":memory:") as store:
        out = await cli._aggiorna(store, Settings(archivio_path=tmp_path / "a.sqlite3"))
        assert chiamate == ["gu.SG", "normattiva"]  # S4 not tried after the stop
        assert out["gu.SG.fermato"] and out["normattiva.atti_nuovi"] == 3
        assert store.get_stato("gu.SG.fermato")
