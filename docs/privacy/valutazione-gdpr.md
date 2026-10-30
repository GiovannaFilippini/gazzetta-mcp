# Valutazione GDPR dell'archivio pubblico (decisione 090)

> BOZZA di lavoro, non un parere legale. Prima di aprire l'archivio al pubblico va riletta da una
> persona esperta di protezione dei dati. Le scelte finali sono della titolare del progetto.

## 1. Che cosa si valuta

Un archivio ricercabile di atti della Gazzetta Ufficiale e di Normattiva, servito via MCP a chiunque
(decisione 090). Per il Regolamento UE 2016/679 i dati personali resi pubblici restano dati
personali: **archiviarli e renderli ricercabili è un trattamento nuovo**, con una responsabilità
propria, anche se il testo è già pubblico alla fonte. L'uso personale o domestico non vale per un
servizio aperto al pubblico.

## 2. Dove sono le persone nei testi

| Parte | Dati personali tipici | Rischio |
|---|---|---|
| Serie Generale: leggi, decreti | nomi di chi è nominato o incaricato, funzionari | basso-medio: ruoli pubblici, finalità di trasparenza |
| Normattiva (atti normativi) | quasi nessuno | basso |
| Concorsi ed esami (S4) | bandi: commissioni; **graduatorie**: elenchi di nomi e punteggi | **medio-alto**: elenchi di persone, ricercabili per nome |
| Parte II (inserzioni) | avvisi, procedure, aste: nomi, talvolta dati che riguardano condanne o situazioni economiche | **alto**: possibili dati di categorie delicate (art. 9-10) |
| Corte costituzionale (S1), regioni (S3), UE (S2) | in prevalenza ruoli e atti, parti spesso già anonimizzate | basso-medio |

## 3. Base giuridica e bilanciamento

Base proposta: **legittimo interesse** (art. 6, par. 1, lett. f). Interesse: accesso gratuito e
cercabile a testi ufficiali pubblici. Test in tre domande:

1. **Interesse legittimo?** Sì: accesso alle informazioni pubbliche, trasparenza.
2. **Necessario?** Per leggi e decreti sì. Per **graduatorie e inserzioni** meno: la finalità si
   raggiunge anche senza archiviarle, perché restano consultabili alla fonte.
3. **Prevale l'interesse della persona?** Per l'elenco di nomi con esiti di concorsi e per i dati
   delle inserzioni il bilanciamento è **incerto**: il rischio di ricerca "per nome" e di
   profilazione cresce quando i testi sono raccolti e indicizzati.

## 4. Obblighi da rispettare

- **Informativa** (art. 14): pubblicata, vedi `informativa.md`. La raccolta non è fatta presso
  l'interessato; l'eccezione per sforzo sproporzionato (art. 14, par. 5, lett. b) non va data per
  scontata: l'informativa pubblica e la procedura di rimozione sono il rimedio.
- **Diritti** (artt. 15-21): rimozione su richiesta con risposta entro un mese (art. 12, par. 3),
  già realizzata tecnicamente (`python -m gazzetta_mcp.archivio rimuovi`), con blocco del
  riscaricamento e registro delle rimozioni (codice, motivo breve, data; nessun testo, nessun
  dato di chi chiede). Le copie di sicurezza già fatte non vengono toccate: dopo un ripristino la
  rimozione va ripetuta (procedura in `deploy/README.md`).
- **Minimizzazione e limitazione** (art. 5): non archiviare ciò che non serve alla finalità.
- **Sicurezza** (art. 32): accesso in sola lettura, limiti di richieste, TLS, nessun log del testo
  delle ricerche, backup protetti.
- **Valutazione d'impatto (art. 35):** da verificare con un esperto se, con graduatorie o Parte II,
  il trattamento su larga scala di dati di persone la renda necessaria. Con il solo ambito
  prudente (sezione 6) è meno probabile, ma non lo escludo io.
- **Registro dei trattamenti** (art. 30): da valutare con l'esperto.

## 5. Misure già nel progetto

Archivio non indicizzato dai motori (`robots.txt`), accesso solo via MCP, limite di richieste per
IP, query e risultati con tetti, sola lettura, nessuna conservazione delle ricerche, procedura di
rimozione con blocco dei ritorni, avvertenza "non ufficiale" in ogni risposta, attribuzione CC BY 4.0.

## 6. Scelte possibili per l'apertura

| Scelta | Rischio | Lavoro |
|---|---|---|
| **A. Prudente:** solo Serie Generale e Normattiva; fuori Parte II e S4 | basso | fatto: filtro nel servizio (`--serie SG`) e acquisizione limitata di default alla Serie Generale |
| B. Tutto, come nella decisione 090 | alto | richiesta di rimozione sempre pronta, valutazione d'impatto, parere esperto |
| C. Nessun accesso pubblico | nullo | l'archivio resta per uso privato |

**Raccomandazione: A**, rivalutata dopo alcuni mesi in base alle richieste ricevute e al parere
dell'esperto. Si possono aggiungere serie in un secondo momento; togliere dati già diffusi è più
difficile.

**Riempimento su richiesta (`--riempi`, spento di default).** Se acceso, un utente anonimo fa archiviare atti chiedendoli: l'archivio cresce per richiesta e non solo per la nostra scelta. Va acceso solo con `--serie SG` (ambito A), perche' gli atti archiviati in questo modo restano nell'archivio e sono soggetti alla stessa procedura di rimozione. Non e' richiesto per aprire il servizio: si puo' tenere spento.

## 7. Da fare prima dell'apertura

1. Decidere la scelta (titolare del progetto).
2. Completare `informativa.md`: contatto, fornitore e paese, tempo di conservazione dei backup, data.
3. Filtro sulle serie nel servizio pubblico (ambito A): **implementato** (opzione `--serie SG`, di
   serie nell'unità systemd). L'acquisizione automatica limitata alla sola Serie Generale è **in
   arrivo** in un altro lavoro: finché non c'è, le altre serie possono essere scaricate e stare nel
   file, ma il servizio non le mostra. La rimozione su richiesta è **implementata**.
4. Verificare i log del server web: nessun IP o contenuto di ricerca conservato oltre il necessario.
5. Far leggere questa valutazione e l'informativa a una persona competente.
6. Pubblicare l'informativa e collegarla dal README e dalle risposte del servizio.
