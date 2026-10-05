from __future__ import annotations

import subprocess
import sys

import httpx
import pytest

from gazzetta_mcp.config import Settings
from gazzetta_mcp.diagnostics import prova, svuota_cache

from ._service_helpers import FIX


def _settings(tmp_path):
    return Settings(cache_path=tmp_path / "sub" / "cache.sqlite3")


def _transport(status=200, body=None, counter=None):
    content = body if body is not None else (FIX / "rss_SG.xml").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if counter is not None:
            counter.append(str(request.url))
        return httpx.Response(status, content=content)

    return httpx.MockTransport(handler)


def test_prova_all_ok_makes_exactly_one_request(tmp_path):
    lines: list[str] = []
    seen: list[str] = []
    code = prova(_settings(tmp_path), out=lines.append, transport=_transport(counter=seen))
    text = "\n".join(lines)
    assert code == 0 and "[KO]" not in text and text.count("[OK]") == 4
    assert seen == ["https://www.gazzettaufficiale.it/rss/SG"]
    assert "Tutto a posto" in text


def test_prova_connection_error_is_friendly(tmp_path):
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    lines: list[str] = []
    code = prova(_settings(tmp_path), out=lines.append, transport=httpx.MockTransport(boom))
    text = "\n".join(lines)
    assert code == 1 and "[KO] Non riesco a collegarmi" in text
    assert "Traceback" not in text and "no route" not in text


def test_prova_http_error_and_unexpected_body(tmp_path):
    lines: list[str] = []
    assert prova(_settings(tmp_path), out=lines.append, transport=_transport(503)) == 1
    assert "503" in "\n".join(lines)
    lines.clear()
    assert prova(_settings(tmp_path), out=lines.append, transport=_transport(200, b"<html>")) == 1
    assert "inatteso" in "\n".join(lines)


def test_prova_unwritable_cache_path(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    settings = Settings(cache_path=blocker / "cache.sqlite3")  # parent is a file
    lines: list[str] = []
    code = prova(settings, out=lines.append, transport=_transport())
    text = "\n".join(lines)
    assert code == 1 and "[KO] Non posso scrivere" in text and "GAZZETTA_MCP_CACHE_PATH" in text


def test_svuota_cache_needs_confirmation(tmp_path):
    settings = _settings(tmp_path)
    settings.cache_path.parent.mkdir(parents=True)
    settings.cache_path.write_text("data")
    lines: list[str] = []
    assert svuota_cache(settings, out=lines.append) == 1
    assert settings.cache_path.exists() and "--si" in "\n".join(lines)
    assert svuota_cache(settings, confermato=True, out=lines.append) == 0
    assert not settings.cache_path.exists()
    assert svuota_cache(settings, out=lines.append) == 0  # already empty


@pytest.mark.parametrize("flag", ["--prova", "--svuota-cache"])
def test_cli_flags_are_listed_in_help(flag):
    out = subprocess.run(
        [sys.executable, "-m", "gazzetta_mcp.server", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert flag in out.stdout
