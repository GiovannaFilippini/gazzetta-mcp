# 020 — Pulizia del testo degli atti

- **Contesto:** il testo di un atto sta in un `<pre>` a larghezza fissa: righe spezzate a mano (circa 70 caratteri), spazi doppi di giustificazione, titoli centrati con molti spazi, apostrofi ASCII al posto delle lettere accentate (`e'`, `sovranita'`). Per la lettura da parte di un LLM va riflusso in paragrafi, senza cambiare il contenuto.
- **Principio:** la pulizia agisce solo sugli spazi e sugli a capo. Non si aggiungono, non si tolgono e non si cambiano parole, cifre o punteggiatura. L'unica eccezione e' il trattino di sillabazione a fine riga, rimosso solo quando la parola intera e' provata (regola 5). Un test verifica che `testo.split()` coincida con quello del `<pre>` originale sul campione reale.
- **Implementazione:** `src/gazzetta_mcp/parsing/text.py` (`extract_pre`, `clean_text`).

## Regole, in ordine

1. **Estrazione:** si prende il primo `<pre>` non vuoto della pagina `/atto/.../caricaArticoloDefault/...` (entita' HTML decodificate). Se la pagina non ha `<pre>`, si usa il testo del `<body>`. Decodifica byte: UTF-8, poi Windows-1252 se non valido.
2. **Normalizzazione di base:** `\r\n` e `\r` diventano `\n`; lo spazio non separabile (`U+00A0`) diventa spazio; le tabulazioni si espandono a 8 colonne; gli spazi a fine riga si tolgono.
3. **Titoli centrati:** una riga con rientro di almeno 10 spazi (`CENTERED_MIN_INDENT`) e' un titolo (`Art. 1`, `Decreta:`, intestazione dell'organo). Resta su una riga propria; piu' righe centrate consecutive restano separate da `\n` dentro lo stesso blocco.
4. **Paragrafi:** si apre un nuovo paragrafo (a) dopo una riga vuota, (b) quando la riga ha un rientro da 1 a 9 spazi (il testo ufficiale rientra di 2 spazi il primo rigo di ogni capoverso), (c) quando la riga inizia con un marcatore di elenco (`a)`, `1)`, `1.`, `-`) e la riga precedente finisce con `.` `;` `:` `?` `!`. Il vincolo (c) evita di spezzare frasi come `n.` / `59`. Un paragrafo spezzato in piu' del necessario non perde contenuto; uno fuso male si': per questo la scelta e' prudente. I paragrafi sono separati da una riga vuota.
5. **Sillabazione a fine riga:** se una riga finisce con lettera/cifra + `-` e la successiva continua, (a) se la successiva inizia con minuscola e la parola unita (senza trattino) compare gia' intera altrove nello stesso testo (fuori dai punti di spezzatura), il trattino si toglie (`ammini-` + `strazione` -> `amministrazione`); (b) altrimenti il trattino resta e le due parti si uniscono senza spazio (`decreto-` + `legge` -> `decreto-legge`; `Friuli-` + `Venezia`; `2020-` + `2021`). Una parola non provata mantiene il trattino: e' meno bello ma fedele. Un trattino preceduto da spazio (` -`) non e' sillabazione: si unisce con uno spazio.
6. **Spazi:** le sequenze di 2 o piu' spazi dentro una riga diventano uno spazio. Limite noto: eventuali tabelle ASCII in `<pre>` perdono l'allineamento; per averle intatte usare la modalita' `raw`.
7. **Accenti:** nessuna correzione. `e'` resta `e'`, `sovranita'` resta `sovranita'`. Indovinare gli accenti e' rischioso (`e'` puo' essere `e'` troncato, `po'`, apostrofo vero in `dell'`, citazioni) e il testo fedele ha la precedenza. Gli apostrofi veri e le virgolette `«»` non si toccano.
8. **Fine:** paragrafi uniti con `\n\n`, spazi iniziali e finali tolti.

## Come tornare indietro

- **Per singola richiesta / in codice:** `GuParser(raw_text=True)` (oppure `parse_atto(..., raw_text=True)`, `clean_text(pre, raw=True)`) restituisce il testo del `<pre>` identico a quello estratto, senza alcuna regola. Il flag e' pensato per essere collegato a una variabile `GAZZETTA_MCP_*` dal servizio (non toccata qui).
- **Per disattivare una sola regola:** ogni regola e' una condizione isolata in `clean_text` (rientro: `CENTERED_MIN_INDENT`; elenchi: `_LIST_MARKER`; sillabazione: `_Hyphens.join`, basta far restituire `left + " " + right` o `left + right`). I test in `tests/unit/test_parsing_text.py` documentano ogni regola.
- **Fuori dal parser:** la cache conserva il testo gia' pulito; per ripulire in modo diverso serve riscaricare l'atto (o salvare anche il `raw`, scelta del servizio).
