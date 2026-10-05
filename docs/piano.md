# Piano di lavoro

## Roadmap

| Step | Cosa | Stato |
|---|---|---|
| 1 | Server MCP locale con cache SQLite sul dispositivo (questo documento) | in chiusura: PR #9, prova con un client reale, repo pubblico, PyPI |
| 2 | Servizio remoto con archivio centrale: popolamento massivo, aggiornamento pianificato (cron), riempimento su richiesta; GU + Normattiva | da progettare, vedi decisione 090 |
| 3 | Riassunti generati sul server e cronologie per ambito | dopo lo step 2 |

Le regole d'uso piu' sotto valgono per il client locale dello step 1. Sono una scelta nostra, non un vincolo delle fonti (`docs/fonti.md`); per lo step 2 valgono quelle della decisione 090.


## Architettura (parti sostituibili dietro interfacce in `src/gazzetta_mcp/interfaces.py`)

```
strumenti MCP (tools/)  ->  servizio (service.py)  ->  SourceClient (sources/)   rete: GU, RSS
                                                   ->  Parser (parsing/)         HTML/XML -> modelli
                                                   ->  Cache (cache/)            SQLite + FTS5
                                                   ->  NormattivaLinker          solo link URN
```

- `config.py`: tutta la configurazione da variabili d'ambiente `GAZZETTA_MCP_*`.
- `models.py`: strutture dati condivise (nessuna dipendenza dalle parti).
- `interfaces.py`: contratti (Protocol) tra le parti.

## Attivita' parallele (un branch + worktree + PR ciascuna)

| ID | Branch | Contenuto | Tocca solo |
|---|---|---|---|
| A | `feat/gu-client` | client HTTP GU + RSS, limite richieste, user-agent, cache HTTP via interfaccia | `sources/gu.py`, `sources/ratelimit.py`, `tests/unit/test_sources*` |
| B | `feat/parsers` | parser feed, sommari, testo atti, pulizia per LLM | `parsing/`, `tests/unit/test_parsing*` |
| C | `feat/cache-sqlite` | cache SQLite, FTS5, filtri | `cache/`, `tests/unit/test_cache*` |
| D | `feat/normattiva` | costruzione link URN Normattiva | `sources/normattiva.py`, `tests/unit/test_normattiva*` |
| E | `docs/oss-files` | README, CONTRIBUTING, CODE_OF_CONDUCT, template, CHANGELOG, CI | file in radice, `.github/` |
| F | `feat/mcp-server` | server FastMCP e 6 strumenti (dopo A-D) | `server.py`, `service.py`, `tools/` |

## Sommario(data, serie): trovare il numero

Il numero non e' calcolabile dalla data. Strategia v1: (1) cache; (2) se la data e' quella dell'ultimo numero nel feed RSS, il numero e' nel `<link>` del canale; (3) altrimenti si prova la pagina del numero per tentativi limitati intorno a una stima (ogni tentativo passa dal limite di richieste); (4) se fallisce, errore chiaro con suggerimento di usare `ultime_pubblicazioni`. Dettagli in decisione 006 (da scrivere da A).

## Regole d'uso del client locale (step 1)

Solo su richiesta dell'utente; mai download massivi; cache; limite richieste configurabile; user-agent identificativo; ogni risposta con link ufficiale e avviso "non ufficiale, fa fede solo la GU".
