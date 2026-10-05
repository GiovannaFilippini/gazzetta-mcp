# 071 — Aggiornamento automatico in `cerca` e uso corretto dei limiti

- **Problema:** `cerca` cercava solo nella cache locale: a cache vuota restituiva un messaggio guida e l'utente doveva sapere quali altri strumenti chiamare prima.
- **Scelta:** `cerca` ha il parametro `aggiorna` (predefinito `true`). Se la serie e' SG o S4 (o assente: entrambe) chiama `ensure_recent_sommari` (decisione 070) prima di cercare. La funzione e' ora asincrona.
- **Regole d'uso rispettate:** si agisce solo quando l'utente chiama lo strumento; al massimo 1 richiesta per l'elenco (cache di un'ora) piu' una per numero mancante, con tetto rigido di 12 numeri per chiamata (predefiniti: SG 7, S4 9); ogni richiesta e' distanziata dal limite di frequenza (`GAZZETTA_MCP_RPS`, predefinito 1 al secondo) e salvata in cache; i numeri gia' in cache non costano nulla. Il caso peggiore di una chiamata di `cerca` senza serie e' quindi 2 + 7 + 9 = 18 richieste a freddo, poi zero finche' non esce un nuovo numero.
- **Copertura dichiarata:** la risposta riporta i numeri caricati per serie (dal, al, quantita', richieste effettuate) e precisa che si cercano titoli, enti e riassunti, non il testo completo degli atti.
- **Errori:** un problema di rete durante l'aggiornamento non fa fallire la ricerca: viene aggiunto alle `note` e si cerca in quello che c'e' in cache.
- **Come tornare indietro:** passare `aggiorna=false` (nessuna rete, come prima) oppure revert del PR.
