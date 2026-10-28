# 120 — `novita_argomento`: ricordare l'ultimo controllo di un argomento

- **Contesto:** la specifica chiede uno strumento tipo "cosa e' uscito su appalti dall'ultima volta che l'ho chiesto", appoggiato alla cache locale. Serve quindi una memoria, per argomento, di fino a dove si e' gia' guardato. Restano valide le regole d'uso (decisioni 005, 070, 071): richieste solo su richiesta dell'utente, poche e limitate, nessun dato fuori dal computer.
- **Scelta:**
  1. **Schema v3** della cache SQLite (una sola tabella nuova, nessuna tabella esistente toccata): `novita_controlli(chiave, argomento, serie, coperto_fino, codici, controllato_il)`.
     - `chiave`: parole dell'argomento in minuscolo, senza accenti ne' stopword, ridotte alla radice (`searchtext.stem`) e **ordinate**, piu' la serie. Quindi "Appalti", "appalto", "gli appalti!" e "Edilizia, bonus" / "bonus edilizia" coincidono; la stessa frase su serie diverse e argomenti diversi restano separati (cio' che e' stato coperto cambia con la serie).
     - `coperto_fino`: ultimo **giorno di pubblicazione davvero coperto** (le date degli atti nella cache sono giorni, non orari: la precisione e' al giorno). `codici`: i codici gia' mostrati di quel giorno, cosi' un atto uscito dopo il controllo nello stesso giorno non si perde e uno gia' visto non torna. `controllato_il`: quando l'utente ha chiesto (solo informativo).
  2. **Riuso della ricerca:** lo strumento chiama `GazzettaService.cerca` (aggiornamento limitato come oggi, solo titoli ed enti, archivi compresi) con `dal = coperto_fino`, senza modificare `service.py`; la logica e' in `novita.py`, lo strumento in `tools/novita.py` (`register_novita`). Legge `service._cache/_today/_now` (attributi interni): e' l'aggancio piu' piccolo possibile, senza toccare `service.py`.
  3. **Primo controllo:** nessuna memoria, quindi **ultimi 7 giorni** (`PRIMI_GIORNI`). Scelta prudente: un'ottima parte dei numeri recenti e' gia' coperta dall'aggiornamento automatico (SG ~30 giorni) e una settimana non produce elenchi enormi. La risposta lo dice.
  4. **Il segno avanza solo dove ha senso**, scritto **dopo** aver costruito la risposta:
     - fino all'ultimo giorno coperto dai numeri realmente caricati (per piu' serie, il piu' corto; se una serie attesa non e' stata caricata, nessun avanzamento): mai l'orologio;
     - risposta vuota: avanza lo stesso, ma solo fino alla copertura reale;
     - oltre `limite`: gli atti sono mostrati dal piu' vecchio e il segno si ferma all'ultimo mostrato; gli altri restano "da vedere" (`non_mostrate`);
     - nessun avanzamento (e un avviso nelle note) con `segna_come_letto=false`, copertura sconosciuta (serie senza aggiornamento automatico, cache vuota, numeri non caricati), risultati troppo numerosi (tetto di 100 della ricerca raggiunto), orologio indietro rispetto all'ultimo controllo, copertura piu' vecchia dell'ultimo controllo; il segno non torna mai indietro;
     - atti piu' recenti dell'ultimo numero esaminato (es. da Normattiva): non mostrati ora, compariranno al controllo successivo, cosi' non risultano letti senza essere stati coperti.
  5. **Dichiarato sempre:** periodo cercato (dal / al), se e' il primo controllo, che si cerca in titoli ed enti e non nel testo completo, che la copertura puo' essere parziale, lacune tra l'ultimo controllo e i numeri disponibili, fonte, link e avvertenza.
  6. `clear()` della cache (e `--svuota-cache`) **non** cancella la memoria dei controlli: non e' contenuto scaricato ma il ricordo dell'utente di cosa ha gia' visto. Si cancella con `delete_controllo` o con `DELETE FROM novita_controlli`.
- **Alternative scartate:**
  - *Salvare l'ora attuale come ultimo controllo:* con copertura parziale farebbe risultare "gia' lette" cose mai viste (vietato dalla specifica).
  - *Un file di stato separato:* un secondo posto da gestire, senza migrazioni e senza la transazione della cache.
  - *Ricordare ogni codice visto:* tabella che cresce senza limite; basta il giorno piu' i codici di quel giorno.
  - *Normalizzare solo con minuscole:* "appalto" e "appalti" sarebbero argomenti diversi.
- **Limiti noti:** precisione al giorno; vale la copertura di `cerca` (titoli ed enti, numeri recenti di SG e S4); con piu' di 100 risultati nel periodo lo strumento non segna niente e chiede di restringere.
- **Come tornare indietro:**
  - Revert del merge: una cache v3 aperta da una versione precedente viene rifiutata con il messaggio "schema piu' recente" (comportamento voluto per tutte le migrazioni). La migrazione e' pero' innocua e annullabile a mano, senza perdere cache: `DROP TABLE novita_controlli;` e `PRAGMA user_version = 2;` (con `sqlite3`), oppure cancellare il file di cache (si riscarica). I dati esistenti non sono mai modificati dalla migrazione.
  - Senza revert: basta non usare lo strumento; la tabella resta vuota.
