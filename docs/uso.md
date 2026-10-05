# Guida rapida all'uso

Esempi di richieste da scrivere al tuo assistente dopo aver collegato `gazzetta-mcp`.
Ricorda: i testi sono **non ufficiali e non autentici**; fa fede solo la Gazzetta Ufficiale.
Le richieste partono solo quando le chiedi, con limite di frequenza e cache locale.

## ultime_pubblicazioni(serie, giorni)

- "Mostrami cosa e' stato pubblicato nella Serie Generale negli ultimi 3 giorni."
- "Ci sono novita' nella Corte Costituzionale (S1) nell'ultima settimana?"

## sommario(data, serie)

- "Dammi il sommario della Gazzetta Ufficiale Serie Generale del 2 ottobre 2026."
- "Elenca gli atti del numero del 3 ottobre 2026 della 4a serie speciale."

Se il numero non si trova, usa prima `ultime_pubblicazioni`.

## leggi_atto(codice, data, serie, offset)

- "Leggimi l'atto con codice redazionale 26A05182."
- "Riassumi in tre punti il testo dell'atto 26A05182 e indica il link ufficiale."

Se l'atto non e' ancora in cache serve la data di pubblicazione (AAAA-MM-GG): si ricava con `ultime_pubblicazioni` o `sommario`. I testi molto lunghi sono divisi in pagine (parametro `offset`).

## cerca_concorsi(parole_chiave, regione, aperti, includi_altri_atti, limite)

- "Cerca concorsi per istruttore amministrativo in Toscana."
- "Ci sono bandi per infermiere pubblicati di recente in Lombardia?"
- "Mostrami anche graduatorie e diari delle prove per dirigente medico." (`includi_altri_atti`)

Funziona anche a cache vuota: non servono codici o numeri. Al primo uso scarica (su tua richiesta, con poche richieste distanziate) i sommari dei numeri degli ultimi 30 giorni della 4a serie, di solito 8-9, e li tiene in cache. Si cerca nel titolo e nell'ente di ogni atto, non nel testo del bando. Ogni risposta dice quali numeri sono stati esaminati e quanti bandi, con il link ufficiale di ciascuno: il bando completo (requisiti, scadenza, modalita' di domanda) va letto sul sito ufficiale. La regione e' stimata dal nome dell'ente; gli atti di regione non determinata sono contati a parte. Con `aperti=false` si includono anche i numeri piu' vecchi gia' in cache.

## rimando_normattiva(atto)

- "Dammi il link Normattiva della legge 5 agosto 2026, n. 140."
- "Dove trovo il testo vigente di questo decreto su Normattiva?" (viene costruito solo il link)

## cerca(testo, serie, tipo, dal, al, limite, aggiorna)

- "Cerca la parola 'semplificazione' negli ultimi numeri della Serie Generale."
- "Trova gli atti che citano 'bonus' pubblicati a ottobre 2026."

Con `aggiorna=true` (predefinito) e serie SG, S4 o non indicata, prima scarica i sommari dei numeri recenti non ancora in cache (SG: gli ultimi 7, S4: gli ultimi 9; al massimo 12 per chiamata), quindi funziona anche a cache vuota. Si cerca nei titoli, negli enti e nei riassunti, non nel testo completo degli atti (solo per quelli gia' letti con `leggi_atto`). La risposta dice quali date sono state caricate. Con `aggiorna=false` non si usa la rete e la ricerca copre solo cio' che e' gia' nella cache locale.
