"""List of the issues published in the last 30 days (``/30giorni/<serie>`` pages)."""

from __future__ import annotations

import re
from datetime import date

from ._util import decode

# The pages carry each issue as ...dataPubblicazioneGazzetta=2026-09-08&numeroGazzetta=69
# (also with &amp;) and, in other links, with the compact date 20260908.
_ISSUE = re.compile(
    r"dataPubblicazioneGazzetta=(\d{4})-?(\d{2})-?(\d{2})(?:&amp;|&)numeroGazzetta=(\d+)"
)


def parse_elenco_30giorni(raw: bytes) -> list[tuple[date, int]]:
    """Return the (date, issue number) pairs of the page, newest first, without duplicates.

    An empty or unrecognised page gives an empty list. Impossible dates are ignored.
    """
    if not raw or not raw.strip():
        return []
    found: set[tuple[date, int]] = set()
    for m in _ISSUE.finditer(decode(raw)):
        try:
            found.add((date(int(m[1]), int(m[2]), int(m[3])), int(m[4])))
        except ValueError:
            continue
    return sorted(found, reverse=True)
