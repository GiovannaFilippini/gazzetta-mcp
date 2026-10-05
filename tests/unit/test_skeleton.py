from gazzetta_mcp.config import Settings
from gazzetta_mcp.models import DISCLAIMER, Serie


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("GAZZETTA_MCP_RPS", "0.5")
    assert Settings.from_env().requests_per_second == 0.5


def test_disclaimer_and_series():
    assert "non ufficiale" in DISCLAIMER.lower()
    assert len(Serie) == 7
