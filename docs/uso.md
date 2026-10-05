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

## leggi_atto(codice)

- "Leggimi l'atto con codice redazionale 26A05182."
- "Riassumi in tre punti il testo dell'atto 26A05182 e indica il link ufficiale."

## cerca_concorsi(parole_chiave, regione)

- "Cerca concorsi per istruttore amministrativo in Toscana."
- "Ci sono bandi per infermiere pubblicati di recente in Lombardia?"

## rimando_normattiva(atto)

- "Dammi il link Normattiva della legge 5 agosto 2026, n. 140."
- "Dove trovo il testo vigente di questo decreto su Normattiva?" (viene costruito solo il link)

## cerca(testo, filtri)

- "Cerca negli atti gia' consultati la parola 'semplificazione', solo Serie Generale."
- "Trova nella cache gli atti che citano 'bonus' pubblicati a ottobre 2026."

La ricerca copre solo cio' che e' gia' nella cache locale.
