# Guida rapida all'uso

Esempi di richieste da scrivere al tuo assistente dopo aver collegato `gazzetta-mcp`.
Ricorda: i testi sono **non ufficiali e non autentici**; fa fede solo la Gazzetta Ufficiale.
Le richieste partono solo quando le chiedi, con limite di frequenza e cache locale.

Non devi conoscere codici ne' date: scrivi cosa cerchi con parole tue, l'assistente sceglie lo
strumento e ricorda i codici dei risultati gia' mostrati. I risultati possono essere **parziali**
(pubblicazioni recenti e quanto gia' consultato, non l'intero archivio): l'assistente dovrebbe
dirlo; in caso di dubbio controlla il sito ufficiale.

Qualcosa non va? Lancia `gazzetta-mcp --prova` dal terminale: controlla l'installazione e dice
cosa fare. Per svuotare la memoria locale: `gazzetta-mcp --svuota-cache --si` (vedi README,
"Se qualcosa non funziona").

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

La data non serve: viene ricordata dai risultati gia' visti, oppure cercata tra le ultime pubblicazioni. Per un atto non recente che non e' mai comparso in un risultato, cercalo prima con parole del titolo (`cerca`, `ultime_pubblicazioni`). I testi molto lunghi sono divisi in pagine (parametro `offset`).

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

Con `aggiorna=true` (predefinito) e serie SG, S4 o non indicata, prima scarica i sommari dei numeri recenti non ancora in cache (SG: gli ultimi 24, circa 30 giorni; S4: gli ultimi 9; al massimo 30 per chiamata), quindi funziona anche a cache vuota. Si cerca nei titoli e negli enti (con parole al singolare o plurale indifferenti; se nessun titolo le contiene tutte, ripiega su quelli che ne contengono almeno una), non nel testo completo degli atti (solo per quelli gia' letti con `leggi_atto`). La risposta dice quali date sono state caricate. Con `solo_vigenti=true` (predefinito) gli atti gia' abrogati sono esclusi (usando l'elenco degli abrogati di Normattiva). Senza `dal`, l'archivio Normattiva cerca nell'ultimo anno. Con `periodo="anno"` la cache locale della Serie Generale viene estesa all'indietro di 24 numeri per chiamata fino a un anno: ripeti la ricerca finche' la risposta dice che e' completa. Con `aggiorna=false` non si usa la rete e la ricerca copre solo cio' che e' gia' nella cache locale.
