# 090 — Step 2: archivio remoto con popolamento massivo e aggiornamento pianificato

- **Contesto:** lo step 1 e' un server MCP locale con cache SQLite sul dispositivo. Le regole "solo su richiesta, nessun download massivo, nessuna copia del sito" sono una **scelta di prudenza nostra**, non un vincolo delle fonti: la GU non ha `robots.txt` ne' condizioni d'uso per la consultazione, e l'unica regola scritta e' citare la fonte e il carattere non autentico e gratuito (`docs/fonti.md`). Normattiva consente esplicitamente il download massivo (open data CC BY 4.0).
- **Obiettivo:** gli atti pubblicati non cambiano, quindi non ha senso richiederli alla fonte ogni volta. Un archivio centrale permette di consultarli senza chiamare la GU, di costruire lo storico di un ambito (come e' cambiato nel tempo) e, nello step 3, di generare riassunti e contenuti sul server.
- **Scelta (step 2):** un servizio remoto con archivio centrale.
  - **Popolamento massivo iniziale:** Normattiva dagli open data ufficiali (download massivo e API); GU con un recupero all'indietro dei numeri (sommari e testi, nelle serie in cui il testo esiste), incrementale e riprendibile.
  - **Aggiornamento pianificato (cron):** ogni giorno i numeri nuovi della GU (tutte le serie) e gli aggiornamenti di Normattiva.
  - **Riempimento su richiesta:** un atto chiesto e non ancora archiviato viene preso dalle fonti, archiviato e restituito.
  - **Cache locale invariata:** il server MCP locale mantiene la sua cache SQLite. Ordine di lettura: cache del dispositivo, poi archivio remoto, poi le fonti.
- **Regole per l'acquisizione dalla GU (scelte nostre):** limite di frequenza basso; user-agent identificativo con un contatto; recupero all'indietro in orari di basso traffico; mai riscaricare cio' che e' gia' archiviato (gli atti sono immutabili); su errori, 429 o 5xx ci si ferma e si riprova piu' tardi con attesa crescente. Prima di avviare il recupero all'indietro e' **consigliato informare IPZS** del progetto.
- **Vincolo "gratuito":** la riproduzione dei testi e' consentita indicandone il carattere gratuito. Se il servizio diventasse a pagamento, la ripubblicazione dei testi GU va rivalutata.
- **Fuori da questa decisione (step 3):** riassunti generati sul server e cronologie per ambito. Avranno una decisione propria.
- **Da decidere prima di implementare:** hosting e database; accesso (pubblico, con chiave); costi; profondita' del recupero all'indietro della GU (da misurare: numeri, atti e richieste per anno); collegamento (solo API usata dal client locale, oppure anche un MCP remoto).
- **Rapporto con le decisioni precedenti:** 005 (Normattiva solo link) e 070 (niente scansione dell'archivio) restano valide per il client locale dello step 1; per il servizio remoto sono superate da questa decisione.
- **Come tornare indietro:** il servizio remoto e' un componente nuovo; il client locale continua a funzionare da solo, senza archivio remoto.
