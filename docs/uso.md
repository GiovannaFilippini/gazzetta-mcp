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

## cerca_concorsi(parole_chiave, regione)

- "Cerca concorsi per istruttore amministrativo in Toscana."
- "Ci sono bandi per infermiere pubblicati di recente in Lombardia?"

## rimando_normattiva(atto)

- "Dammi il link Normattiva della legge 5 agosto 2026, n. 140."
- "Dove trovo il testo vigente di questo decreto su Normattiva?" (viene costruito solo il link)

## cerca(testo, serie, tipo, dal, al, limite)

- "Cerca negli atti gia' consultati la parola 'semplificazione', solo Serie Generale."
- "Trova nella cache gli atti che citano 'bonus' pubblicati a ottobre 2026."

La ricerca copre solo cio' che e' gia' nella cache locale.
