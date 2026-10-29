# Riepilogo del progetto gazzetta-mcp

## Cosa è stato costruito

Un piccolo programma gratuito che gira sul tuo computer e permette a un assistente AI di consultare e cercare nella Gazzetta Ufficiale italiana. L'assistente può:

1. vedere le **ultime pubblicazioni** di una serie (`ultime_pubblicazioni`);
2. leggere l'**indice di un numero** (`sommario`);
3. leggere il **testo di un atto**, ripulito per essere più leggibile (`leggi_atto`);
4. cercare **concorsi** (`cerca_concorsi`);
5. trovare il **collegamento a Normattiva** di una legge o di un decreto (`rimando_normattiva`);
6. **cercare nel testo** di tutto ciò che il programma ha già scaricato (`cerca`).

Il programma scarica dal sito solo quando glielo si chiede, non copia l'archivio, ricorda quello che ha già letto (così non rifà le stesse richieste), rallenta le richieste (una al secondo) e si presenta al sito con un nome chiaro. Ogni risposta riporta il link ufficiale e ricorda che il testo **non è ufficiale**: fa fede solo la Gazzetta Ufficiale.

Il repository GitHub è **privato**: `GiovannaFilippini/gazzetta-mcp`. Non è stato pubblicato niente su PyPI.

## Come provarlo, passo per passo

1. Installa `uv` (https://docs.astral.sh/uv/) se non lo hai già.
2. Scarica il progetto: `git clone https://github.com/GiovannaFilippini/gazzetta-mcp` e entra nella cartella.
3. Controlla che funzioni: `uv sync`, poi `uv run pytest` (i test non usano internet) e `uv run gazzetta-mcp --version`.
4. Collegalo a Claude Code: `claude mcp add gazzetta -- uv run --directory <percorso della cartella> gazzetta-mcp`.
   Per Claude Desktop trovi l'esempio di configurazione nel `README.md`.
5. Chiedi all'assistente, per esempio: «Quali sono le ultime pubblicazioni della Serie Generale?», «Leggimi l'atto 26A05182», «Dammi il link Normattiva della legge 241/1990».
   Altri esempi sono in `docs/uso.md`.

Quando il pacchetto sarà su PyPI basterà `uvx gazzetta-mcp`.

## Cosa è stato verificato sul sito

Gli indirizzi, il feed RSS e il testo degli atti sono stati controllati con richieste reali il 5 ottobre 2026. I dettagli e le differenze rispetto alle guide di terzi sono in `docs/fonti.md`. In sintesi:

- il numero della Gazzetta non si ricava dalla data, quindi il programma lo cerca con poche prove limitate;
- il sito risponde «tutto bene» anche per un numero che non esiste, quindi ogni tentativo viene controllato nel contenuto della pagina;
- il testo degli atti è disponibile per Serie Generale, Corte Costituzionale, Regioni e Concorsi. Per Unione Europea, Contratti pubblici e Parte II il sito non ha la pagina di testo, e il programma lo dice chiaramente invece di provare.

Regole d'uso lette: GU e Normattiva consentono la riproduzione se si cita la fonte e si dichiara che il testo è non autentico e gratuito. Normattiva offre anche dati aperti (licenza CC BY 4.0) dal 2026: **non usati nella prima versione** (vedi sotto).

## Decisioni prese

| N. | Decisione | File |
|---|---|---|
| 001 | Nome `gazzetta-mcp` (libero su PyPI e GitHub) | [001](decisioni/001-nome-pacchetto.md) |
| 002 | Licenza MIT | [002](decisioni/002-licenza-mit.md) |
| 003 | Tecnologie: Python, FastMCP, httpx, SQLite | [003](decisioni/003-stack-python.md) |
| 004 | Impostazioni da variabili d'ambiente | [004](decisioni/004-configurazione-env.md) |
| 005 | Normattiva: solo collegamento nella v1 | [005](decisioni/005-normattiva-solo-link.md) |
| 006 | Flusso di lavoro con git | [006](decisioni/006-commit-e-branch.md) |
| 010 | Come si trova il numero della Gazzetta | [010](decisioni/010-numero-gazzetta.md) |
| 020 | Pulizia del testo degli atti | [020](decisioni/020-pulizia-testo.md) |
| 021 | Libreria per leggere le pagine | [021](decisioni/021-parser-selectolax.md) |
| 030 | Memoria locale e ricerca | [030](decisioni/030-cache-sqlite-fts5.md) |
| 040 | Link Normattiva senza data | [040](decisioni/040-normattiva-urn-senza-data.md) |
| 050 | Pubblicazione su PyPI preparata ma spenta | [050](decisioni/050-release-non-attivo.md) |
| 060 | Server MCP, strumenti e limiti | [060](decisioni/060-server-mcp.md) |
| 070 | Ricerca concorsi da cache vuota (ultimi 30 giorni) | [070](decisioni/070-concorsi-ultimi-30-giorni.md) |
| 071 | Aggiornamento automatico di `cerca` | [071](decisioni/071-aggiornamento-automatico-cerca.md) |
| 090 | Step 2: archivio remoto con popolamento massivo e cron | [090](decisioni/090-archivio-remoto.md) |

Ogni file spiega le alternative scartate e come tornare indietro. Ogni parte (fonti, lettura delle pagine, memoria locale, strumenti) è separata dalle altre: sostituirne una non obbliga a riscrivere il resto.

## Cosa resta aperto o richiede una tua scelta

Mi sono fermato, come richiesto, su queste azioni:

1. **Rendere pubblico il repository.** Ora è privato. Prima conviene rileggere `README.md` e sostituire il segnaposto `<owner>` con `GiovannaFilippini`.
2. **Pubblicare su PyPI.** Il flusso è pronto in `.github/workflows/release.yml` ma si avvia solo a mano. Prima serve configurare su PyPI il «trusted publisher» (nessun token da salvare) e creare l'ambiente `pypi` su GitHub: i passi sono in decisione 050.
3. **Verifica manuale con un client reale.** Ho provato il server con test automatici e con un avvio reale, ma non con un assistente vero collegato per giornate di uso. Conviene un giro di prova.
4. **Possibili sviluppi:** importare i dati aperti di Normattiva per il testo vigente (decisione 005); migliorare il riconoscimento del numero della Gazzetta per date lontane; testo di Unione Europea, Contratti pubblici e Parte II (oggi non disponibile); ricerca per prefisso (`gat*`), oggi assente.
5. **Piccoli limiti noti:** nella pulizia del testo le tabelle in caratteri semplici perdono l'allineamento (esiste la modalità «testo originale»); `cerca_concorsi` copre i numeri degli ultimi 30 giorni (decisione 070), non l'archivio; il Codice di condotta è stato scritto a memoria dal testo Contributor Covenant 2.1 e andrebbe confrontato con l'originale.
6. **Attivare gli aggiornamenti automatici dei test** (CI) è già fatto per ogni pull request; controlla che i test passino su GitHub alla prima esecuzione.
