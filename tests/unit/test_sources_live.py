import pytest

from gazzetta_mcp.config import Settings
from gazzetta_mcp.models import Serie
from gazzetta_mcp.sources.gu import GuClient, parse_feed_channel


@pytest.mark.live
async def test_live_rss_sg():
    settings = Settings(user_agent="gazzetta-mcp-dev/0.1")
    async with GuClient(settings) as client:
        page = await client.get_feed(Serie.SG)
    assert b"<rss" in page.content
    channel = parse_feed_channel(page.content)
    assert channel is not None
    assert channel[1] > 0


@pytest.mark.live
async def test_live_elenco_30giorni_s4():
    """One polite request to the real site: the index of the last 30 days lists issues."""
    from gazzetta_mcp.parsing import parse_elenco_30giorni

    settings = Settings(user_agent="gazzetta-mcp-dev/0.1")
    async with GuClient(settings) as client:
        page = await client.get_elenco_30giorni(Serie.S4)
    issues = parse_elenco_30giorni(page.content)
    assert 3 <= len(issues) <= 15
    assert issues == sorted(issues, reverse=True)
