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
