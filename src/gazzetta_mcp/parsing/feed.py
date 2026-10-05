"""RSS 2.0 feed of a GU series."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime
from email.utils import parsedate_to_datetime

from ..models import Feed, FeedItem, Serie
from ._util import ELI_GU, ELI_ID, ParseError, https, split_trailing_code, squash

_CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"


def _text(el: ET.Element | None) -> str:
    return "" if el is None or el.text is None else el.text


def _pub(value: str) -> datetime | None:
    try:
        return parsedate_to_datetime(value.strip()) if value.strip() else None
    except (TypeError, ValueError):
        return None


def parse_feed(raw: bytes, serie: Serie) -> Feed:
    """Parse an RSS feed. Raises ParseError if it is not a feed with a recognisable channel."""
    if not raw or not raw.strip():
        raise ParseError("empty feed")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ParseError(f"feed is not valid XML: {exc}") from exc
    channel = root.find("channel")
    if channel is None:
        raise ParseError("feed has no <channel>")

    link = https(_text(channel.find("link")))
    m = ELI_GU.search(link)
    if not m:
        raise ParseError("channel <link> does not contain /eli/gu/AAAA/MM/GG/NUM/SERIE")
    data = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    numero = int(m.group(4))

    items: list[FeedItem] = []
    for it in channel.findall("item"):
        ilink = https(_text(it.find("link")))
        titolo = squash(_text(it.find("title")))
        riassunto, code_in_text = split_trailing_code(_text(it.find(_CONTENT)))
        im = ELI_ID.search(ilink)
        if im:
            idata = date(int(im.group(1)), int(im.group(2)), int(im.group(3)))
            codice = im.group(4)
        else:
            idata = data
            codice = code_in_text or ""
        if not codice:
            continue  # nothing identifies this entry: skip rather than invent
        items.append(
            FeedItem(
                codice=codice,
                serie=serie,
                data=idata,
                titolo=titolo,
                riassunto=riassunto,
                link=ilink,
                pubblicato=_pub(_text(it.find("pubDate"))),
            )
        )
    return Feed(serie=serie, numero=numero, data=data, link=link, items=items)
