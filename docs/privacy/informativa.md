# Informativa sulla protezione dei dati personali — archivio gazzetta-mcp

> BOZZA. Va completata (segnaposto tra parentesi quadre) e fatta rileggere da una persona esperta
> prima di aprire l'archivio al pubblico. Vale per il servizio remoto dell'archivio. Il server
> locale installato sul proprio computer, di serie, non invia dati a nessuno. Fa eccezione la
> funzione facoltativa che lo collega al servizio remoto: è **spenta di default** e si accende
> solo se chi lo usa imposta `GAZZETTA_MCP_ARCHIVIO_URL`. In quel caso il server locale invia al
> servizio il testo delle ricerche (al massimo 200 caratteri) e i codici degli atti che si
> leggono, insieme all'indirizzo IP di rete (vedi «Cosa NON facciamo»).

## Chi tratta i dati

Titolare del trattamento: **Giovanna Filippini**, che gestisce il progetto open source gazzetta-mcp
a titolo personale. Contatto per le richieste sui dati: **[INDIRIZZO EMAIL DEDICATO]**.

## Quali dati e da dove vengono

L'archivio contiene copie di testi **già pubblici**: gli atti della Gazzetta Ufficiale della
Repubblica Italiana (gazzettaufficiale.it) e gli atti normativi di Normattiva (dati aperti con
licenza CC BY 4.0). Questi testi possono contenere dati personali, per esempio il nome di chi è
nominato o incaricato in un decreto. I dati non sono raccolti dalle persone interessate: vengono dalle
fonti pubbliche indicate.

Portata: **solo la Serie Generale della Gazzetta Ufficiale e gli atti normativi di Normattiva**.
Il servizio acquisisce e mostra solo questi. Non sono inclusi la Parte II (inserzioni), i concorsi
(con le graduatorie) e le altre serie, salvo diversa comunicazione su questa pagina. Se in passato
altri testi fossero stati archiviati per prova, non sono comunque consultabili tramite il servizio.

## Perché e con quale base giuridica

- **Finalità:** rendere consultabili e cercabili, gratuitamente e con un assistente AI, testi
  ufficiali già pubblici, citando sempre la fonte.
- **Base giuridica:** legittimo interesse (art. 6, par. 1, lett. f, del Regolamento UE 2016/679)
  all'accesso a informazioni pubbliche. È stata fatta una valutazione di bilanciamento
  (`docs/privacy/valutazione-gdpr.md`).
- Il servizio non crea profili di persone, non fa decisioni automatiche e non vende né cede dati.

## Cosa NON facciamo

- L'archivio non è indicizzato dai motori di ricerca: si interroga solo con strumenti MCP.
- Non conserviamo il testo delle ricerche né i codici degli atti letti. Per limitare gli abusi si tiene in memoria, per pochi
  minuti, un contatore di richieste per indirizzo IP; non viene scritto su disco.
  **[DA VERIFICARE ALLA MESSA IN OPERA: nessun log del server web con gli IP, o conservazione breve]**

**Se usa il server locale collegato al servizio.** Solo se imposta `GAZZETTA_MCP_ARCHIVIO_URL`
(è spento di default), le ricerche che fa e i codici degli atti che apre vengono inviati al
servizio per avere la risposta, come ogni richiesta web arriva con il suo indirizzo IP. Il
servizio li usa per rispondere e non li conserva. Se non imposta quella variabile, il server
locale non contatta il servizio.

## Con chi sono condivisi

Il testo è consultabile da chiunque usi il servizio. Per far funzionare il servizio ci si avvale del
fornitore dell'infrastruttura **[NOME FORNITORE E PAESE]**, che tratta i dati per nostro conto.
**[Se fuori dallo Spazio economico europeo, indicare le garanzie.]**

## Per quanto tempo

Gli atti restano nell'archivio finché sono pubblicati dalla fonte, salvo richiesta di rimozione
accolta. Le copie di sicurezza (backup) sono conservate per **[N giorni]** e poi eliminate.

Di ogni rimozione si conserva un **registro** con il codice dell'atto, un motivo breve e la data.
Il registro non contiene il testo dell'atto né dati di chi ha fatto la richiesta (nome, email); serve
a non riscaricare l'atto e a ripetere la rimozione se si ripristina una copia di sicurezza. Il
registro è presente anche nelle copie di sicurezza.

## I suoi diritti

Può chiedere l'accesso ai dati, la rettifica, la **cancellazione**, la limitazione e può **opporsi**
al trattamento (artt. 15-21 del Regolamento) scrivendo a **[INDIRIZZO EMAIL DEDICATO]**,
indicando il codice dell'atto (per esempio `26A05182`) o il link ufficiale, e il motivo.

- Rispondiamo **entro un mese**.
- Se la richiesta è accolta, l'atto viene **cancellato dall'archivio e non viene più riscaricato**; i
  dati restano nella fonte ufficiale, che non dipende da noi.
- Non possiamo né aggiornare né cancellare le copie che si trovano nella memoria locale
  (cache) di chi usa il server locale sul proprio computer, né le copie di sicurezza già fatte da
  altri. Le copie di sicurezza nostre vengono eliminate alla scadenza indicata sopra, e se se ne
  ripristina una si ripete la rimozione. Dalla prossima versione del programma, gli atti letti
  dal servizio remoto non verranno più salvati nella cache locale.

Può inoltre proporre reclamo al Garante per la protezione dei dati personali (garanteprivacy.it).

## Aggiornamenti

Data di questa versione: **[DATA]**. Ogni modifica sostanziale è riportata sul repository del progetto.
