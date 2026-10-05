# 001 — Nome del pacchetto

- **Contesto:** il nome di lavoro e' `gazzetta-mcp`.
- **Scelta:** `gazzetta-mcp` (PyPI) / `gazzetta_mcp` (modulo) / repository `gazzetta-mcp`. Verificato il 2026-10-05: su PyPI `https://pypi.org/pypi/gazzetta-mcp/json` risponde 404 (libero); su GitHub nessun repository con quel nome nell'account.
- **Alternative scartate:** `gu-mcp`, `gazzetta-ufficiale-mcp` (meno chiari / piu' lunghi).
- **Come tornare indietro:** rinominare `name` in `pyproject.toml`, la cartella `src/gazzetta_mcp` e gli import; `gh repo rename`. Circa 30 minuti, prima della pubblicazione su PyPI.
