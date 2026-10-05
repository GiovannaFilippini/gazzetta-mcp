# 010 — Come si trova il numero della Gazzetta

- **Problema:** `sommario(data, serie)` richiede il numero del fascicolo, che non si calcola dalla data.
- **Scelta** (`resolve_numero` in `sources/gu.py`), in ordine, fermandosi al primo esito:
  1. cache locale (sommario gia' scaricato per quella data e serie);
  2. feed RSS della serie: il `<link>` del canale e' `/eli/gu/AAAA/MM/GG/NUM/SERIE/html`; se la data coincide con quella dell'ultimo numero, il numero e' quello (1 richiesta);
  3. data precedente (entro un anno): al massimo 4 tentativi (parametro `max_guesses`) intorno a una stima `numero_ultimo - giorni * frequenza` (SG circa 6/7 al giorno, altre serie circa 2/7), ordinati per distanza dalla stima; ogni tentativo passa dal limite di richieste;
  4. altrimenti `NumeroNotFoundError` con il suggerimento di usare le ultime pubblicazioni. Date future rispetto al feed: errore diretto.
- **Verifica di un tentativo:** il sito risponde **200 anche con un numero sbagliato** (verificato con `/eli/gu/2026/10/03/999/SG/html`): restituisce una pagina vuota di circa 11 KB. Quindi non basta il codice HTTP: la pagina e' valida solo se contiene il permalink `dataPubblicazioneGazzetta=AAAA-MM-GG&numeroGazzetta=NUM` con data e numero richiesti (`sommario_matches`).
- **Limiti noti:** la stima e' approssimata (festivita', numeri doppi, supplementi); fuori dai pochi tentativi si preferisce fallire con un messaggio chiaro piuttosto che scorrere molte pagine. Nessun ciclo su molte pagine.
