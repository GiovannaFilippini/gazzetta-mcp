# 004 — Configurazione da variabili d'ambiente

- **Scelta:** tutti i valori modificabili stanno in `config.py` e si leggono da variabili `GAZZETTA_MCP_*` (URL di base, richieste al secondo, percorso della cache, user-agent, timeout). Nessun valore fisso altrove.
- **Alternative scartate:** file di configurazione TOML (piu' codice, nessun vantaggio per la v1).
- **Come tornare indietro:** cambia solo `config.py`.
