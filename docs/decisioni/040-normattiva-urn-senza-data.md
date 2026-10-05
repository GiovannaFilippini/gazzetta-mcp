# 040 — Normattiva: URN abbreviato "anno;numero" quando manca la data

- **Contesto:** gli utenti citano spesso gli atti come `l. 241/1990` o `DL 144/2026`, senza data completa. L'URN canonico richiede `AAAA-MM-GG`.
- **Verifica (2026-10-05, una sola richiesta, user-agent `gazzetta-mcp-dev/0.1`):** `https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:1990;241` risponde 200 e mostra "LEGGE 7 agosto 1990, n. 241". La forma con solo l'anno e' quindi accettata (verificata per `legge`; per gli altri tipi e' assunta per analogia).
- **Scelta:** `NormattivaLinkBuilder` (in `sources/normattiva.py`) estrae tipo, data e numero dal testo libero. Con data completa produce l'URN canonico; con `numero/anno` produce `urn:nir:stato:<tipo>:<anno>;<numero>` e lo segnala nella nota. Nessun accesso di rete. Un codice redazionale GU (es. `26G00123`) da solo non identifica l'atto: si restituisce il link alla pagina di ricerca (`/ricerca/semplice`, non verificata con una richiesta) con una nota esplicativa. Testo non interpretabile: `ValueError` in italiano.
- **Alternative scartate:** risolvere la data interrogando Normattiva (rete, fuori ambito v1); rifiutare le citazioni senza data.
- **Come tornare indietro / estendere:** nuovi tipi di atto si aggiungono alla tabella `_TYPES`; l'import via API open data resta un `NormattivaLinker` alternativo (vedi 005).
