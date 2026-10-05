# 003 — Stack: Python 3.10+, FastMCP, httpx, sqlite3, uv/hatchling

- **Contesto:** stack indicato dalla richiesta.
- **Scelta:** Python >= 3.10; pacchetto `fastmcp`; `httpx`; `sqlite3` della libreria standard con FTS5; parsing HTML con `selectolax` o `beautifulsoup4` (scelta dell'agente B, da registrare); build con `hatchling`; gestione con `uv`; test `pytest`; lint `ruff`.
- **Alternative scartate:** SDK `mcp` ufficiale diretto (piu' verboso), `requests` (niente async).
- **Come tornare indietro:** il server e' confinato in `server.py` e `tools/`; sostituire FastMCP tocca solo quei file (circa 2 ore).
