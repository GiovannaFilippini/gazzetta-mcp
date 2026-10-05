# 090 — Step 2: archivio remoto con popolamento massivo e aggiornamento pianificato

- **Contesto:** lo step 1 e' un server MCP locale con cache SQLite sul dispositivo. Le regole "solo su richiesta, nessun download massivo, nessuna copia del sito" sono una **scelta di prudenza nostra**, non un vincolo delle fonti: la GU non ha `robots.txt` ne' condizioni d'uso per la consultazione, e l'unica regola scritta e' citare la fonte e il carattere non autentico e gratuito (`docs/fonti.md`). Normattiva consente esplicitamente il download massivo (open data CC BY 4.0).
- **Obiettivo:** gli atti pubblicati non cambiano, quindi non ha senso richiederli alla fonte ogni volta. Un archivio centrale permette di consultarli senza chiamare la GU, di costruire lo storico di un ambito (come e' cambiato nel tempo) e, nello step 3, di generare riassunti e contenuti sul server.

## Scelte

- **Ambito:** tutta la Gazzetta Ufficiale, tutte le serie, piu' Normattiva.
- **Popolamento massivo iniziale e aggiornamento pianificato (cron):** ogni giorno i numeri nuovi della GU e gli aggiornamenti di Normattiva; recupero all'indietro dell'archivio GU incrementale e riprendibile, dai numeri piu' recenti verso i piu' vecchi.
- **Riempimento su richiesta:** un atto chiesto e non ancora archiviato viene preso dalle fonti, archiviato e restituito.
- **Cache locale invariata:** il server MCP locale mantiene la sua cache SQLite. Ordine di lettura: cache del dispositivo, poi archivio remoto, poi le fonti. Se l'archivio remoto non risponde, il client locale ripiega sulle fonti come nello step 1.
- **Ogni dato dalla fonte che lo ha:** Normattiva non contiene tutta la Gazzetta, ma solo gli atti normativi dello Stato (leggi, decreti-legge, decreti legislativi, DPR e parte dei regolamenti), cioe' una parte della Serie Generale; in cambio ha il testo vigente, le versioni nel tempo e i rapporti di modifica, che la GU non ha. Per questi atti si usa Normattiva (download massivo consentito); dalla GU si scarica il resto (decreti ministeriali, comunicati, serie 1-5, Parte II). Lo stesso atto si riconosce nelle due fonti dall'identificativo URN/ELI. La sovrapposizione reale va misurata sui dati.
- **Collegamenti tra atti (modello a grafo):** atti come nodi, rapporti come archi tipizzati (`modifica`, `abroga`, `rettifica`, `errata_corrige`, `cita`, `attua`). Fonti degli archi: i rapporti di modifica di Normattiva; per la GU, errata corrige e rettifiche e i riferimenti estratti dal testo. Il grafo serve allo storico di un ambito. Proposta di realizzazione: tabella degli archi in Postgres con query ricorsive, senza un database a grafo dedicato (meno manutenzione); da riverificare insieme all'hosting.
- **Dati personali:** scelta del progetto: si archivia tutto, Parte II e graduatorie comprese, perche' i testi sono pubblici. Nota di rischio: per il GDPR i dati personali resi pubblici restano dati personali, e il loro riuso in un archivio ricercabile e' un trattamento autonomo. Accorgimenti a costo basso consigliati: archivio non indicizzato dai motori di ricerca (accesso solo via MCP), procedura di rimozione su richiesta, informativa privacy. Da riconsiderare prima dell'apertura al pubblico.
- **IPZS:** contatto facoltativo, da valutare se il recupero all'indietro crea problemi o se serve un canale dati diretto.
- **Accesso:** pubblico, solo via MCP. Non si puo' imporre davvero (il client e' open source, una chiave nel client e' pubblica): il servizio remoto parla solo MCP, con limite di richieste per IP ed eventualmente una chiave anonima generata al primo avvio per bloccare gli abusi.

## Fatti verificati (2026-10-05)

- Testo HTML degli atti presente almeno dal 1950 (legge del 1950-01-02, codice `049U0961`); 1946-1949 non verificati.
- Il testo si carica **un articolo per richiesta**: `caricaArticoloDefault` restituisce il primo, gli altri sono elencati da `/atto/vediMenuHTML` (link `caricaArticolo?...&art.idArticolo=N`). Un atto di 18 articoli costa circa 20 richieste.
- La GU non offre API ne' open data (solo RSS). Le API ufficiali sono quelle di Normattiva.

## Acquisizione dalla GU (regole nostre)

- Limite di frequenza basso; user-agent identificativo con un contatto; recupero all'indietro in orari di basso traffico; mai riscaricare cio' che e' gia' archiviato (gli atti sono immutabili); su errori, 429 o 5xx ci si ferma e si riprova piu' tardi con attesa crescente.
- **Durata:** con un articolo per richiesta e 1 richiesta al secondo, tutta la GU e' nell'ordine di milioni di richieste, cioe' mesi. Da misurare per anno (numeri, atti, articoli) prima di fissare la frequenza.
- **Controllo del parser:** il sito puo' cambiare le pagine senza preavviso. Il cron verifica ogni giorno su pagine campione che il parser estragga ancora i campi attesi e manda un avviso se fallisce o se un numero risulta vuoto.

## Hosting (proposta, da riverificare)

- **Carico atteso:** basso. Anche 10.000 utenti a 20 domande al giorno sono circa 2-3 richieste al secondo; il dimensionamento dipende dallo spazio (stima: decine di GB per tutta la GU, da misurare) e dall'acquisizione, non dal traffico.
- **Requisito:** manutenzione minima, niente server da gestire.
- **Proposta:** Postgres gestito (es. Supabase: ricerca testuale con radici italiane, pgvector per lo step 3) e acquisizione con cron su GitHub Actions che riusa il codice Python esistente.
- **Alternativa:** SQLite + FTS5 (lo schema che abbiamo) su una piccola macchina (es. Fly.io) con backup continuo: costa meno, un po' piu' di manutenzione.
- Prezzi e limiti dei piani da verificare al momento della scelta.

## Fuori da questa decisione (step 3)

Riassunti generati sul server e cronologie per ambito. Avranno una decisione propria; i riassunti generati dall'AI dovranno essere dichiarati come tali.

## Rapporto con le decisioni precedenti e ritorno indietro

- 005 (Normattiva solo link) e 070 (niente scansione dell'archivio) restano valide per il client locale dello step 1; per il servizio remoto sono superate da questa decisione.
- Il servizio remoto e' un componente nuovo; il client locale continua a funzionare da solo, senza archivio remoto.
