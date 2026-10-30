# Far partire l'archivio sul tuo PC con Windows

Questa guida serve per riempire l'archivio **sul tuo computer**, a costo zero, senza aprire nulla a
internet. L'archivio resta un file privato tuo. Quando e se vorrai metterlo su un server (cartella
`deploy/`), il file si potra' portare li'.

**Prima di cominciare**
- Il PC deve restare **acceso e collegato a internet** durante le corse. Le attivita'
  pianificate possono anche risvegliarlo dalla sospensione.
- Il lavoro e' lento di proposito: il programma fa **una richiesta al secondo** al sito della
  Gazzetta, per rispetto. Ti servono giorni, non ore. Puoi usare il PC normalmente intanto.
- Non scarica nulla che non sia gia' pubblico, e non lo scarica due volte.
- Tempi e spazio sono **stime dalla prova** (una prova con 29 atti ha prodotto un file di circa
  2 MB): un anno di Serie Generale potrebbe richiedere **5-10 ore di corse** e **100-400 MB**.
  Le misuriamo dopo il primo lotto.

Tutti i comandi si scrivono in **PowerShell** (cerca "PowerShell" nel menu Start).

---

## Passo 1 — Metti il progetto aggiornato

1. Apri PowerShell e scrivi:
   ```
   cd C:\Users\Utente\Desktop\gazzetta-mcp
   ```
2. Poi:
   ```
   git switch main
   git pull
   ```
   **Cosa dovresti vedere:** `Already up to date` oppure un elenco di file aggiornati.
3. Controlla che `uv` funzioni:
   ```
   uv --version
   ```
   **Cosa dovresti vedere:** un numero di versione, per esempio `uv 0.12.22`.

## Passo 2 — Prova che il comando risponda

```
.\deploy\windows\lavoro.ps1 -Comando stato
```

**Cosa dovresti vedere:** `Nessun archivio in ...: niente da mostrare o controllare.` Va bene:
l'archivio non esiste ancora, lo crea il primo aggiornamento.

Se Windows risponde che "l'esecuzione di script e' disabilitata", scrivi una volta sola:
```
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```
e rispondi `S`. Poi ripeti il comando.

## Passo 3 — Il primo lotto piccolo (circa mezz'ora)

```
.\deploy\windows\lavoro.ps1 -Comando recupera -Argomenti "--max-numeri 3 --max-atti 30"
```

Scarica **3 numeri della Gazzetta** e fino a **30 atti da Normattiva**. Mentre lavora scrive righe
sullo schermo; **non chiudere la finestra** finche' non torna il segno `PS C:\...>`.

**Cosa dovresti vedere alla fine:** un blocco con dei numeri, per esempio `"gu.SG.atti_nuovi": 41`
e `"normattiva.atti_nuovi": 30`. Se c'e' una riga con `fermato`, il sito ha rallentato o ha detto
"troppe richieste": e' normale, il programma si e' fermato da solo con prudenza. Riprova piu' tardi.

## Passo 4 — Guarda cosa c'e' nell'archivio

```
.\deploy\windows\lavoro.ps1 -Comando stato
```

**Cosa dovresti vedere:** il numero di atti (`"atti"`), quanti numeri sono da fare (`"da_fare"`) e
quanti fatti (`"fatto"`).

Il file dell'archivio e' qui: `%LOCALAPPDATA%\gazzetta-mcp\archivio.sqlite3`. Per vedere quanto pesa:
```
(Get-Item "$env:LOCALAPPDATA\gazzetta-mcp\archivio.sqlite3").Length / 1MB
```
(il risultato e' in megabyte). **Scrivimelo**: mi serve per rifare la stima dello spazio.

Per controllare che il programma legga ancora bene le pagine della Gazzetta:
```
.\deploy\windows\lavoro.ps1 -Comando controlla
```
**Cosa dovresti vedere:** un riepilogo che finisce con l'esito. Se dice "FALLITO", non e' grave:
dimmelo e guardo cosa e' cambiato.

## Passo 5 — Fallo andare da solo ogni notte

```
.\deploy\windows\installa-pianificazione.ps1
```

Crea due attivita' in "Utilita' di pianificazione", **senza** bisogno di essere amministratore:
- `GazzettaArchivio-Aggiorna`, ogni giorno alle **05:30**: i numeri nuovi.
- `GazzettaArchivio-Recupera`, ogni giorno alle **01:00**: un lotto di numeri piu' vecchi
  (40 numeri e 300 atti alla volta).

**Cosa dovresti vedere:** due righe `Creata: ...`. Per vederle: menu Start > "Utilita' di
pianificazione" > "Libreria". Per provarne una subito:
```
Start-ScheduledTask -TaskName GazzettaArchivio-Aggiorna
```

Se non vuoi piu' le attivita': `.\deploy\windows\rimuovi-pianificazione.ps1`.

**Attenzione:** le attivita' partono solo se il PC e' acceso o in sospensione. Se lo spegni, la
corsa salta e riparte la notte dopo: non si perde niente, si va solo piu' piano.

## Passo 6 — Controllare che vada bene (ogni tanto)

- **Cosa e' successo:** i registri sono in `%LOCALAPPDATA%\gazzetta-mcp\log` (gli ultimi 30). Aprine
  uno con il Blocco note.
- **Quanto manca:** `.\deploy\windows\lavoro.ps1 -Comando stato` ti dice quanti numeri sono
  `da_fare`. Quando sono 0, il recupero ha finito quello che sa.
- **Un anno nuovo:** il programma attraversa il 31 dicembre da solo, ma se non riesce a determinare
  il numero finale dell'anno si ferma e lo scrive in `note_dei_lavori` (nello `stato`) con le
  parole "non determinabile". In quel caso scrivimelo.

## Passo 7 — Copia di sicurezza

```
.\deploy\windows\backup-archivio.ps1
```
Crea un file `.zip` in `Documenti\gazzetta-backup` e tiene le ultime 7. Fallo ogni tanto. Se c'e' un
lavoro in corso, aspetta e riprova dopo.

## Passo 8 — Se qualcuno chiede di togliere un atto

Prima ferma le attivita' pianificate:
```
Stop-ScheduledTask -TaskName GazzettaArchivio-Recupera
Stop-ScheduledTask -TaskName GazzettaArchivio-Aggiorna
```
Poi vedi cosa cancelleresti (e' solo un'anteprima):
```
uv run python -m gazzetta_mcp.archivio rimuovi 26A05182 --motivo richiesta-interessato
```
e, se e' l'atto giusto, cancella davvero:
```
uv run python -m gazzetta_mcp.archivio rimuovi 26A05182 --motivo richiesta-interessato --si
```
- Nel motivo non scrivere mai il nome o l'email di chi ha chiesto: i valori ammessi sono
  `richiesta-interessato`, `errore` e `altro`.
- L'atto non verra' piu' riscaricato. Le copie di sicurezza gia' fatte lo contengono ancora:
  eliminale o sostituiscile.

## Cosa questa guida NON fa

- Non mette l'archivio su internet e non lo condivide con nessuno.
- Il programma sul tuo PC (Claude Desktop con la Gazzetta) leggera' questo archivio **solo dopo
  una nuova versione** del pacchetto (0.3.0): l'estensione che hai ora e' la 0.2.0, che non lo
  conosce.
- Non e' ancora l'archivio pubblico: per quello servono l'informativa privacy completata e la
  rilettura di una persona esperta (vedi `docs/privacy/`).
