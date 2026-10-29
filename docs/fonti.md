# Fonti dati: verifica e condizioni d'uso

Verifica eseguita il 2026-10-05 con richieste reali (poche, distanziate, user-agent identificativo).

## Gazzetta Ufficiale (gazzettaufficiale.it)

### Schemi di indirizzo verificati

| Cosa | Schema | Esito |
|---|---|---|
| Sommario di un numero | `/eli/gu/AAAA/MM/GG/NUMERO/SERIE/html` | OK (200). Anche senza `/html` si arriva alla stessa pagina. |
| PDF di un numero | `/eli/gu/AAAA/MM/GG/NUMERO/SERIE/pdf` | OK (200, application/pdf) |
| Scheda di un atto | `/eli/id/AAAA/MM/GG/CODICE/SERIE` | OK (200) |
| Testo di un atto | `/atto/<serie_url>/caricaArticoloDefault/originario?atto.dataPubblicazioneGazzetta=AAAA-MM-GG&atto.codiceRedazionale=CODICE&atto.tipoProvvedimento=TIPO` | OK (200). Il testo e' dentro un `<pre>` |
| Menu degli articoli di un atto | `/atto/vediMenuHTML?atto.dataPubblicazioneGazzetta=AAAA-MM-GG&atto.codiceRedazionale=CODICE&tipoSerie=<serie_url>&tipoVigenza=originario` | OK (200). Elenca articoli e allegati e contiene il modulo di esportazione `menuExportForm`. Comunicati e concorsi non hanno articoli nel menu |
| Testo intero di un atto | `POST /atto/stampa/<serie_url>/originario` con i campi del modulo (`articoliSelected` per ogni articolo e allegato, piu' i campi nascosti) | OK (200), verificato il 2026-10-05 anche senza cookie di sessione. Tutti gli articoli e gli allegati in una pagina, un `<pre>` per elemento dentro `div.wrapper_pre` |
| Elenco dei numeri degli ultimi 30 giorni | `/30giorni/serie_generale`, `/30giorni/concorsi` | OK (200). Ogni numero ha link con `dataPubblicazioneGazzetta=AAAA-MM-GG&numeroGazzetta=NN`; gli altri nomi di serie non sono stati verificati (decisione 070) |
| Feed RSS | `/rss/SG`, `/rss/S1` ... `/rss/S5`, `/rss/P2` | OK (200, application/rss+xml) |

### Differenze rispetto allo schema "da documentazione di terzi"

- La sigla della serie sul sito reale e' **maiuscola** (`SG`, `S4`). Il sito accetta anche le minuscole, ma i link ufficiali (RSS) usano le maiuscole: usiamo le maiuscole.
- Lo schema `/eli/id/.../CODICE/SERIE` e `/eli/gu/.../NUMERO/SERIE` e' confermato. Il suffisso `/ita/html` per gli atti **non** funziona (404).
- Il numero della Gazzetta **non si puo' calcolare dalla data**: va letto dal feed RSS (campo `<link>` del canale) o dalla pagina. Per `sommario(data, serie)` serve quindi una strategia di ricerca del numero (vedi `docs/piano.md`).
- **`caricaArticoloDefault` restituisce solo il primo articolo** (verificato il 2026-10-05 sulla L. 240/1990, 18 articoli, e su `26A05182`, 2 articoli e un allegato). Il testo intero si ottiene con il modulo di esportazione del menu: menu + esportazione = 2 richieste per atto, qualunque sia il numero di articoli. Gli atti senza articoli nel menu (es. comunicati) hanno tutto il testo nella pagina singola.
- La pagina dell'atto carica il testo in un iframe: il testo vero sta nell'indirizzo `/atto/<serie_url>/caricaArticoloDefault/originario?...`. Per la Serie Generale `<serie_url>` e' `serie_generale`, per i concorsi `concorsi`. Verificati il 2026-10-05 sulle pagine reali degli atti: `S1` -> `corte_costituzionale`, `S3` -> `regioni`. Per `S5` (contratti pubblici) e `P2` (inserzioni) la pagina dell'atto non contiene il riquadro `/atto/.../caricaArticoloDefault` (il client restituisce un errore chiaro `UnsupportedSerieError`); `S2` (Unione Europea) ha nel feed solo link a PDF paginati (`/do/gazzetta/unione_europea/...`), valore non verificato.
- Il sito risponde 200 anche per un numero di fascicolo inesistente (pagina vuota): vedi `docs/decisioni/010-numero-gazzetta.md`.
- Sigle delle serie (dai feed RSS ufficiali): `SG` Serie Generale, `S1` Corte Costituzionale, `S2` Unione Europea, `S3` Regioni, `S4` Concorsi ed esami, `S5` Contratti pubblici, `P2` Parte II (inserzioni).
- Codici redazionali: `26A05182` (anno 2 cifre + lettera della rubrica + progressivo). Nella 4a serie la lettera e' `E`.

### Condizioni d'uso

- Non esiste un `robots.txt` (la richiesta restituisce la pagina 404 del sito).
- Non c'e' una pagina "condizioni generali" per i testi consultabili: l'unica regola esplicita, riportata nelle pagine, e':
  > "L'unico testo definitivo e' quello pubblicato sulla Gazzetta Ufficiale a mezzo stampa, che prevale in caso di discordanza. La riproduzione dei testi forniti nel formato elettronico e' consentita purche' venga menzionata la fonte, il carattere non autentico e gratuito."
- Non c'e' un portale open data ufficiale della GU. L'unico canale dichiarato per le novita' e' il feed RSS.
- Le condizioni generali trovate (inserzioni.gazzettaufficiale.it) riguardano il servizio di pubblicazione inserzioni, non la consultazione.

**Conseguenze per il codice:** obbligatorio (dalla fonte): citare sempre fonte e link ufficiale; dichiarare "non autentico" e "gratuito". Scelte di prudenza nostre (la fonte non le impone): per il client locale nessun download massivo; limite di richieste; user-agent identificativo. Il servizio remoto dello step 2 fa popolamento massivo con regole proprie (decisione 090).

## Normattiva (normattiva.it)

- Note legali (`/staticPage/legal`):
  > "I testi presenti nella banca dati 'Normattiva' non hanno carattere di ufficialita'. L'unico testo ufficiale e definitivo e' quello pubblicato sulla Gazzetta Ufficiale Italiana." — "La riproduzione dei testi forniti nel formato elettronico e' consentita purche' venga menzionata la fonte, il carattere non autentico e gratuito."
- Collegamento permanente: `https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:<tipo>:<AAAA-MM-GG>;<numero>` (verificato: 200). Esempio: `urn:nir:stato:legge:2026-08-05;140`.
- **Open data ufficiale:** `https://dati.normattiva.it` — dal 1 gennaio 2026 i dati degli atti (originario, vigente, multivigente) sono scaricabili con licenza **CC BY 4.0**, con download massivo e API. Documentazione API: `https://dati.normattiva.it/assets/come_fare_per/API_Normattiva_OpenData.pdf`. Linee guida ELI: `https://dati.normattiva.it/assets/come_fare_per/ELI_implementation_in_Italy.pdf`.

**Decisione per la v1:** `rimando_normattiva` costruisce solo il link URN (nessun download). Dopo la v1 questo e' cambiato in due punti, sempre senza download massivo: `cerca` interroga l'API open data per la ricerca nell'archivio (decisione 072) e `testo_vigente` legge **un articolo per volta** dall'API (decisione 110, con attribuzione CC BY 4.0). L'import massivo da `dati.normattiva.it` resta **fuori dalla v1** ed e' annotato come sviluppo possibile (vedi `docs/decisioni/005-normattiva-solo-link.md`).

## Campioni salvati

In `tests/fixtures/real/` ci sono feed RSS, sommari, schede e un testo di atto reali (2026-10-02/03), usati dai test senza rete. Il PDF di un numero (2,3 MB) non e' incluso.
