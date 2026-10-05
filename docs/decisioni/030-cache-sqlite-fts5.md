# 030 — Cache SQLite con FTS5

- **Scelta:** `cache/sqlite.py` (`SqliteCache`), solo libreria standard `sqlite3`, una connessione per oggetto (`check_same_thread=False`) protetta da un `RLock`. Percorso da `Settings.cache_path` (cartelle create al volo; `:memory:` ammesso).
- **Schema:** tabelle `http_pages`, `feeds`/`feed_items`, `sommari`/`sommario_voci`, `atti`, piu' `docs` + tabella FTS5 `docs_fts` (titolo, emettitore, testo; tokenizer `unicode61 remove_diacritics 2`, quindi "citta" trova "città"). Ogni atto, voce di sommario e item di feed gia' in cache e' indicizzato; per ogni codice `search()` restituisce un solo risultato (vince il testo integrale).
- **TTL:** solo per pagine HTTP (da `fetched_at` della pagina) e feed (da quando e' stato salvato). Sommari e atti sono immutabili, senza scadenza. L'orologio e' iniettabile per i test.
- **Query:** il testo utente diventa termini tra virgolette in AND (`"a" "b"`); tutto cio' che non e' parola viene scartato, quindi `AND`, `*`, `"`, `:` non sono mai sintassi FTS5. Nessuna ricerca per prefisso in v1. Punteggio = `-bm25` (piu' alto e' meglio), titolo pesato x4.
- **Migrazioni:** `PRAGMA user_version` + lista `_MIGRATIONS` (una voce per versione, mai modificare le esistenti, solo aggiungere). Ogni passo e' transazionale; un database piu' nuovo del codice produce `CacheError`.
- **FTS5 assente:** `CacheError` con messaggio chiaro all'apertura.
- **Come tornare indietro:** la cache e' un file ricostruibile: basta cancellarlo (o `SqliteCache.clear()`).
