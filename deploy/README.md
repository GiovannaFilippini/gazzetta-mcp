# Mettere l'archivio in produzione su un piccolo server

Questa guida e' scritta per una persona che non e' tecnica. Si fa un passo alla volta: per ogni
passo c'e' il comando da incollare e **cosa dovresti vedere**. Se vedi altro, fermati e
guarda "Se qualcosa non va" in fondo.

Cosa si costruisce (decisione `docs/decisioni/090-archivio-remoto.md`, sezioni "Hosting" e "Accesso"):

```
Internet --(443, HTTPS)--> Caddy --(127.0.0.1:8080)--> servizio MCP in sola lettura --> archivio.sqlite3
                                                                                          ^
                      lavori notturni (aggiorna, recupera, controlla) scrivono qui -------+
```

- Un solo server Linux (Debian o Ubuntu), l'archivio e' un file SQLite sul suo disco.
- **Caddy** ottiene da solo il certificato HTTPS e protegge il servizio.
- Il servizio MCP legge soltanto; i lavori programmati scrivono.
- Copia di sicurezza ogni notte.

Tempo: circa un'ora per l'installazione. Il riempimento dell'archivio storico richiede poi
**settimane** (e' normale, e' fatto apposta lento per rispetto verso il sito della Gazzetta).

> **Importante, stato del software.** La parte "archivio" (`gazzetta_mcp.archivio`) non e' ancora
> nella versione pubblicata su PyPI (0.2.0): e' nel ramo principale di GitHub. Finche' non esce una
> versione successiva, il passo 8 installa da GitHub. Quando esce, basta sostituire una riga
> (indicata nel passo 8).

Ogni comando che comincia con `sudo` chiede i permessi di amministratore. Se il provider ti da'
direttamente l'utente `root`, `sudo` funziona lo stesso.

---

## Prima di cominciare: cosa devi avere

1. **Un dominio** (per esempio `archivio.tuodominio.it`) di cui puoi modificare i record DNS.
   Serve un nome vero: il certificato HTTPS non si puo' avere su un numero.
2. **Un'email di contatto**. Finisce in due posti: nell'"identita'" con cui il programma si
   presenta alla Gazzetta Ufficiale (cosi' possono scriverti se danno fastidio le richieste) e
   nell'avviso di scadenza dei certificati.
3. **Un provider** dove noleggiare il server (passo 1) e un metodo di pagamento.
4. Un computer da cui lavori (Windows, Mac o Linux) con un terminale: su Windows "PowerShell".
5. Un servizio per ricevere gli avvisi (facoltativo, passo "Monitoraggio minimo").

Segna da parte, mentre procedi: l'indirizzo IP del server, il nome del dominio, l'email.
Nei comandi seguenti sostituisci:

- `IP-DEL-SERVER` con l'indirizzo IP che ti da' il provider;
- `UTENTE` con il nome utente di accesso (spesso `root` su Debian, `ubuntu` su Ubuntu);
- `archivio.example.org` con il tuo dominio;
- `contatto@example.org` con la tua email.

---

## Passo 1. Scegliere e creare il server

Non do' prezzi: cambiano e vanno verificati sul sito del provider al momento dell'acquisto.
Quando confronti le offerte, **chiedi/controlla** queste cose:

| Cosa | Perche' |
|---|---|
| Sistema operativo **Debian 12** (o piu' recente) oppure **Ubuntu 22.04 / 24.04 LTS** | Questa guida e i file sono pensati per loro |
| 1-2 processori, **2 GB di memoria**, **almeno 40 GB di disco** | Il carico di visite e' basso; conta lo spazio. La dimensione dell'archivio completo **non e' ancora stata misurata** (stima nel documento 090: "decine di GB"), quindi meglio un disco ampliabile o scegli di piu' |
| Il disco si puo' **ingrandire** dopo senza rifare tutto | Se l'archivio cresce piu' del previsto |
| Server in **Unione Europea** | Ci sono testi con dati personali (Parte II, graduatorie): meglio restare in UE |
| Indirizzo **IPv4** (e, se c'e', IPv6) fisso | Il dominio punta li' |
| Accesso con **chiave SSH** gia' alla creazione | Niente password (passo 2) |
| Traffico incluso e **nessun blocco delle porte 80 e 443 in uscita ed ingresso** | Serve per HTTPS e per scaricare dalle fonti |
| Snapshot/backup del provider (facoltativo) | Comodo in piu', non sostituisce il passo "Backup" |

Alla creazione ti chiedera' (nomi variano): sistema operativo -> Debian/Ubuntu; piano; regione ->
UE; **chiave SSH** -> quella del passo 2 (puoi anche fare il passo 2 prima); nome del server -> ad
esempio `gazzetta-archivio`. Alla fine otterrai un **indirizzo IP**.

**Cosa dovresti vedere:** il server nell'elenco del provider con stato "in esecuzione" e un
indirizzo IP.

---

## Passo 2. Accesso con chiave SSH (niente password)

Una "chiave" sono due file: uno pubblico (si da' al server) e uno privato (resta solo sul tuo
computer e non si manda a nessuno).

**Sul tuo computer** (PowerShell su Windows, Terminale su Mac/Linux):

```
ssh-keygen -t ed25519 -C "archivio-gazzetta"
```

Premi Invio alle domande per accettare il percorso proposto. Ti chiede una "passphrase": e' una
password che protegge il file privato; mettila (e conservala).

**Cosa dovresti vedere:** un messaggio con "Your public key has been saved in ...id_ed25519.pub".

Per mostrare la parte pubblica (da incollare nel modulo del provider):

- Mac/Linux: `cat ~/.ssh/id_ed25519.pub`
- Windows PowerShell: `type $env:USERPROFILE\.ssh\id_ed25519.pub`

E' una sola riga che comincia con `ssh-ed25519`. Incollala nel campo "chiave SSH" del provider.

Se il server e' gia' creato con una password, aggiungi la chiave cosi' (dal tuo computer):
`ssh-copy-id UTENTE@IP-DEL-SERVER` (su Windows non c'e': incolla la riga nel pannello del provider
oppure chiedi la procedura al supporto).

---

## Passo 3. Primo accesso e aggiornamento del sistema

Dal tuo computer:

```
ssh UTENTE@IP-DEL-SERVER
```

La prima volta chiede "Are you sure you want to continue connecting?": scrivi `yes`.
**Cosa dovresti vedere:** il prompt del server (qualcosa come `utente@gazzetta-archivio:~$`).

Da qui in avanti tutti i comandi si incollano **sul server**. Aggiorna il sistema:

```
sudo apt update
sudo apt -y upgrade
sudo apt -y install ufw unattended-upgrades git curl sqlite3 python3 util-linux
```

**Cosa dovresti vedere:** scorrono molte righe e alla fine si torna al prompt senza "E:" (errori).
Se dice che serve un riavvio: `sudo reboot`, aspetta un minuto e rientra con `ssh`.

---

## Passo 4. Spegnere l'accesso con password

**Prima** controlla che l'accesso con chiave funzioni davvero (sei gia' entrato con la chiave? se
al passo 3 non ti ha chiesto la password del server ma solo la passphrase della chiave, si').
Poi:

```
sudo tee /etc/ssh/sshd_config.d/10-solo-chiave.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
sudo sshd -t && sudo systemctl reload ssh
```

**Cosa dovresti vedere:** nessun messaggio. **Non chiudere questa finestra.** Apri una seconda
finestra e prova `ssh UTENTE@IP-DEL-SERVER`: deve entrare. Se non entra, correggi dalla prima
finestra (cancella il file: `sudo rm /etc/ssh/sshd_config.d/10-solo-chiave.conf` e
`sudo systemctl reload ssh`).

(Su alcune versioni il servizio si chiama `sshd` invece di `ssh`: se il comando da' errore, riprova
con `sudo systemctl reload sshd`.)

---

## Passo 5. Aggiornamenti automatici di sicurezza

```
sudo tee /etc/apt/apt.conf.d/20auto-upgrades >/dev/null <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
sudo systemctl enable --now unattended-upgrades
```

**Cosa dovresti vedere:** nessun errore. Verifica: `systemctl is-enabled unattended-upgrades`
risponde `enabled`.

Questi aggiornamenti installano solo le correzioni di sicurezza. Ogni tanto (una volta al mese,
dopo gli avvisi) entra e fai `sudo reboot` se il sistema lo richiede (`ls /var/run/reboot-required`
esiste).

---

## Passo 6. Firewall: aperte solo le porte 22, 80 e 443

L'ordine conta: prima si permette SSH, poi si accende, altrimenti ti chiudi fuori.

```
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status verbose
```

(Se il provider ha un suo firewall nel pannello, apri la stessa lista: 22, 80, 443.)

**Cosa dovresti vedere:** `Status: active` e le tre porte con `ALLOW IN`. La finestra SSH resta
attiva. La porta 8080 del servizio **non** e' aperta (e' giusto: ascolta solo dentro il server).

---

## Passo 7. Utenti senza privilegi e cartella dei dati

Si creano **due utenti di sistema** che non possono entrare con una shell, e **un gruppo comune**
(vedi "Perche' due utenti e un gruppo" piu' sotto):

```
sudo groupadd --system gazzetta-dati
sudo useradd --system --gid gazzetta-dati --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin gazzetta
sudo useradd --system --gid gazzetta-dati --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin gazzetta-web
```

Cartella dei dati, con il bit "setgid" (`2770`: i file nuovi restano del gruppo `gazzetta-dati`),
cartella delle copie e cartella di configurazione:

```
sudo install -d -o gazzetta -g gazzetta-dati -m 2770 /var/lib/gazzetta-archivio
sudo install -o gazzetta -g gazzetta-dati -m 0660 /dev/null /var/lib/gazzetta-archivio/.lavori.lock
sudo install -d -o gazzetta -g gazzetta-dati -m 0755 /var/backups/gazzetta-archivio
sudo install -d -o root -g gazzetta-dati -m 0750 /etc/gazzetta-archivio
```

Il file `.lavori.lock` e' il "lucchetto" che impedisce a due lavori di scrivere insieme.

**Cosa dovresti vedere:** nessun messaggio. Verifica con `ls -ld /var/lib/gazzetta-archivio`:
deve cominciare con `drwxrws---` e dire `gazzetta gazzetta-dati`.

---

## Passo 8. Installare `uv` e il programma

`uv` e' lo strumento che installa Python e i pacchetti. Installazione ufficiale, in una cartella
visibile a tutti gli utenti:

```
curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
uv --version
```

**Cosa dovresti vedere:** `uv` con un numero di versione. (Se `uv` non si trova, chiudi e riapri
la sessione SSH; se continua, guarda "Se qualcosa non va".)

Il programma va in un suo ambiente isolato, **di proprieta' dell'amministratore** (i servizi lo
possono eseguire ma non modificarlo). Si usa il Python del sistema, non uno scaricato nella
cartella di un utente:

```
sudo mkdir -p /opt/gazzetta-mcp
sudo uv venv --python /usr/bin/python3 /opt/gazzetta-mcp/venv
```

Poi **una** di queste due, a seconda del caso:

**A) Da GitHub** (oggi, perche' la parte archivio non e' ancora su PyPI):

```
sudo uv pip install --python /opt/gazzetta-mcp/venv/bin/python "git+https://github.com/GiovannaFilippini/gazzetta-mcp.git"
```

(Per fissare una versione precisa aggiungi `@NOME-DEL-TAG` o `@CODICE-DEL-COMMIT` dopo `.git`.)

**B) Da PyPI** (quando esce una versione che contiene l'archivio):

```
sudo uv pip install --python /opt/gazzetta-mcp/venv/bin/python gazzetta-mcp
```

Verifica che l'archivio ci sia:

```
/opt/gazzetta-mcp/venv/bin/python -m gazzetta_mcp.archivio --help
```

**Cosa dovresti vedere:** un testo d'aiuto con i comandi `aggiorna`, `recupera`, `controlla`,
`stato`. Se dice `No module named gazzetta_mcp.archivio`, hai installato una versione troppo
vecchia (la 0.2.0 di PyPI): usa la via A.

Il programma richiede Python 3.10 o piu' recente; Debian 12 e Ubuntu 22.04 lo hanno gia'.

---

## Passo 9. Installare i file di questo kit

I file del kit (cartella `deploy/`) stanno nel repository. Scaricalo e copia i file ai loro posti:

```
git clone --depth 1 https://github.com/GiovannaFilippini/gazzetta-mcp.git /tmp/gazzetta-kit
cd /tmp/gazzetta-kit/deploy

sudo install -d -m 0755 /usr/local/lib/gazzetta-archivio
sudo install -m 0755 backup.sh avviso.sh disco.sh /usr/local/lib/gazzetta-archivio/
sudo install -m 0755 gazzetta-archivio /usr/local/bin/gazzetta-archivio
sudo install -m 0644 systemd/* /etc/systemd/system/
sudo install -o root -g gazzetta-dati -m 0640 variabili.env.esempio /etc/gazzetta-archivio/variabili.env
cd ~
```

Ora **modifica la configurazione** con un editor semplice (`nano`: si salva con Ctrl+O, Invio,
si esce con Ctrl+X):

```
sudo nano /etc/gazzetta-archivio/variabili.env
```

Cambia **almeno** `contatto@example.org` nella riga `GAZZETTA_MCP_USER_AGENT` con la tua email
vera. Le altre righe vanno bene cosi' (sono spiegate nel file). Le variabili sono quelle che il
codice legge davvero; `AVVISO_URL` e' del kit e si compila dopo (vedi "Monitoraggio minimo").

Poi fai rileggere i servizi:

```
sudo systemctl daemon-reload
```

**Cosa dovresti vedere:** nessun messaggio. Verifica: `systemctl cat gazzetta-archivio.service`
mostra il contenuto del file.

---

## Passo 10. Dominio: i record DNS

Nel pannello di chi gestisce il dominio (il "registrar" o il DNS del provider) crea:

| Tipo | Nome (host) | Valore |
|---|---|---|
| `A` | `archivio` (cioe' `archivio.tuodominio.it`) | l'indirizzo **IPv4** del server |
| `AAAA` | `archivio` | l'indirizzo **IPv6** del server (solo se il provider te ne da' uno) |

Se il tuo dominio e' proprio `archivio.example.org` il "nome" e' `archivio`; se usi il dominio
nudo (`tuodominio.it`) il nome e' `@`. Se usi l'IPv6 devi usarlo per davvero (il firewall del
passo 6 lo copre; se il provider ha un firewall suo, apri 80 e 443 anche per IPv6).

I cambiamenti DNS richiedono da pochi minuti a qualche ora. Controlla dal **tuo** computer:

```
nslookup archivio.tuodominio.it
```

**Cosa dovresti vedere:** l'indirizzo IP del tuo server nella risposta. Se vedi "non-existent
domain" aspetta e riprova. **Non andare avanti finche' non risponde l'IP giusto**, altrimenti
Caddy non riesce a ottenere il certificato (e se insisti troppo Let's Encrypt ti blocca per un po').

---

## Passo 11. Caddy (HTTPS automatico)

Installa Caddy dal suo archivio ufficiale (le istruzioni aggiornate sono su
<https://caddyserver.com/docs/install#debian-ubuntu-raspbian>: se differiscono, valgono quelle):

```
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
```

Metti la nostra configurazione, con il **tuo** dominio e la **tua** email:

```
sudo install -m 0644 /tmp/gazzetta-kit/deploy/Caddyfile /etc/caddy/Caddyfile
sudo sed -i 's/archivio\.example\.org/archivio.tuodominio.it/; s/contatto@example\.org/la-tua@email.it/' /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
```

(Ricorda di scrivere il tuo dominio e la tua email al posto di `archivio.tuodominio.it` e
`la-tua@email.it`.)

**Cosa dovresti vedere:** `Valid configuration`. Caddy parte da solo; ricaricalo con
`sudo systemctl reload caddy`. Non guardera' ancora nulla di utile finche' il servizio non gira.

### Perche' `header_up X-Forwarded-For {remote_host}`

Il servizio limita le richieste **per indirizzo IP**. Dietro un proxy tutte le connessioni
arrivano da `127.0.0.1`, quindi l'indirizzo vero lo si legge dall'intestazione `X-Forwarded-For`
(accensione con `--trust-proxy`). Il servizio legge **l'ultima voce** di quella intestazione,
perche' un proxy fidato aggiunge in coda l'indirizzo che ha visto, mentre le voci davanti
potrebbero essere state scritte dal visitatore.

Caddy, per come e' configurato qui, non si fida di nessuno davanti a se': l'istruzione
`header_up X-Forwarded-For {remote_host}` **sostituisce** qualunque valore mandato dal visitatore
con il solo indirizzo visto sulla connessione. Risultato: l'intestazione contiene sempre una sola
voce, vera. Senza quella riga un visitatore potrebbe mandare `X-Forwarded-For: 1.2.3.4` e
cambiarlo a ogni richiesta, aggirando il limite. **Quindi:** non rimuovere quella riga, non mettere
un altro proxy o una CDN davanti a Caddy senza rivedere questo punto, e non avviare mai il servizio
con `--trust-proxy` senza Caddy davanti (e senza il firewall del passo 6, che impedisce di
raggiungere direttamente la porta 8080).

---

## Passo 12. Primo riempimento e avvio

L'archivio **non esiste ancora**: il servizio in sola lettura rifiuta di partire senza il file, e
lo crea il primo lavoro. Esegui il primo aggiornamento a mano (puo' durare diversi minuti; e' sicuro
ripeterlo):

```
sudo gazzetta-archivio aggiorna
```

**Cosa dovresti vedere:** alla fine un riquadro JSON con righe come `gu.SG.atti_nuovi`,
`normattiva.atti_nuovi`. Dei numeri (anche piccoli) vanno bene. Se invece compare una voce che
finisce con `.fermato` e un motivo, la fonte ha avuto un problema: aspetta un'ora e riprova.
Poi:

```
sudo gazzetta-archivio stato
```

**Cosa dovresti vedere:** un riquadro con `"atti": <numero maggiore di zero>`.

Accendi tutto (servizio e lavori programmati):

```
sudo systemctl enable --now gazzetta-archivio.service
sudo systemctl enable --now gazzetta-aggiorna.timer gazzetta-controlla.timer gazzetta-backup.timer gazzetta-disco.timer
sudo systemctl enable --now gazzetta-recupera@SG.timer
sudo systemctl reload caddy
```

**Cosa dovresti vedere:** nessun errore. Controlla:

```
systemctl status gazzetta-archivio.service --no-pager
systemctl list-timers 'gazzetta-*' --no-pager
```

Il primo mostra `active (running)`; il secondo elenca i 5 timer con la prossima esecuzione.

Il recupero all'indietro parte per la sola serie `SG` (Serie Generale), poche decine di numeri
all'ora di notte. Piu' avanti puoi attivare le altre serie, una alla volta, una volta che la
`SG` va liscia: `sudo systemctl enable --now gazzetta-recupera@S1.timer` (serie ammesse: SG, S1,
S2, S3, S4, S5, P2). Ogni corsa e' limitata in numero (20 numeri e 200 atti di Normattiva) e
non si sovrappone alle altre grazie al lucchetto `.lavori.lock`.

---

## Passo 13. Verifica da fuori

Dal **tuo** computer (non dal server), con il tuo dominio:

```
curl -i https://archivio.tuodominio.it/robots.txt
```

**Cosa dovresti vedere:** `HTTP/2 200` (o `HTTP/1.1 200`), tra le intestazioni
`strict-transport-security` e `x-robots-tag: noindex, nofollow`, e nel corpo:

```
User-agent: *
Disallow: /
```

(Se il certificato non e' ancora pronto la prima volta, aspetta mezzo minuto e riprova.
Se vedi un errore di certificato dopo alcuni minuti, guarda "Se qualcosa non va".)

Verifica anche che il servizio **non** sia raggiungibile saltando Caddy:

```
curl -m 5 http://IP-DEL-SERVER:8080/robots.txt
```

**Cosa dovresti vedere:** nessuna risposta/timeout (la porta 8080 e' chiusa da fuori).

Verifica HTTP -> HTTPS: `curl -i http://archivio.tuodominio.it/robots.txt` risponde con un
reindirizzamento (`308`) verso `https://`.

Prova del servizio vero (lo strumento `stato_archivio`):

```
curl -s https://archivio.tuodominio.it/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"stato_archivio","arguments":{}}}'
```

**Cosa dovresti vedere:** un testo con `"atti"`, `"numeri"` e `"ultimo_aggiornamento"`. (Questo
comando non e' stato provato dal vivo: se risponde con un errore sul "protocollo" e non con i
dati, la strada piu' semplice e' collegare un client MCP al tuo indirizzo `https://.../mcp` e
chiamare `stato_archivio` da li'.)

---

## Cosa controllare dopo l'avvio

Subito, e poi dopo il primo giorno e la prima settimana:

| Cosa | Come | Valore atteso |
|---|---|---|
| Il servizio gira | `systemctl is-active gazzetta-archivio` | `active` |
| Il proxy gira | `systemctl is-active caddy` | `active` |
| HTTPS valido | `curl -I https://archivio.tuodominio.it/robots.txt` | `200` senza avvisi di certificato |
| I timer sono pronti | `systemctl list-timers 'gazzetta-*'` | 5 timer con data della prossima corsa |
| Il primo aggiornamento notturno | il giorno dopo: `journalctl -u gazzetta-aggiorna -n 40 --no-pager` | JSON con `atti_nuovi`, nessun `.fermato` |
| Il recupero avanza | `sudo gazzetta-archivio stato` ogni giorno | `atti` che cresce |
| Il controllo del parser | `journalctl -u gazzetta-controlla -n 20 --no-pager` | esito positivo; nessun avviso |
| La prima copia di sicurezza | `ls -lh /var/backups/gazzetta-archivio` | un file `archivio-AAAA-MM-GG.sqlite3.gz` |
| Nessun log dei contenuti | `sudo journalctl -u caddy -n 50 --no-pager` | niente indirizzi, niente testi di ricerca |
| Il limite per IP funziona | vedi sotto | dopo molte richieste, `429` |

Prova del limite (30 richieste al minuto per IP, raffica di 10; dal tuo computer):

```
for i in $(seq 1 25); do curl -s -o /dev/null -w "%{http_code} " https://archivio.tuodominio.it/robots.txt; done; echo
```

**Cosa dovresti vedere:** all'inizio `200`, poi dopo una decina di richieste ravvicinate qualche
`429`. (Su PowerShell il ciclo e' diverso; il modo piu' facile e' farlo dal server stesso con
`curl` verso il dominio.) Questa prova ti dice anche che il limite funziona sul tuo IP vero e non
su `127.0.0.1`: se avessi 429 anche chiedendo da un'altra connessione contemporaneamente, guarda
"Se qualcosa non va".

---

## Monitoraggio minimo

Tre cose, tutte gratuite o quasi (verifica sul sito del servizio quali limiti ha il piano gratuito
oggi):

1. **Il servizio risponde (uptime).** Iscriviti a un servizio di controllo con piano gratuito
   (per esempio UptimeRobot, Better Stack o simili). Crea un controllo "HTTPS" sull'indirizzo
   `https://archivio.tuodominio.it/robots.txt` ogni 5 minuti, con avviso via email. E' l'indirizzo
   giusto perche' risponde sempre `200` ed e' leggero.
2. **Lo spazio su disco.** E' gia' coperto dal timer `gazzetta-disco.timer`: ogni mattina controlla
   e se il disco e' sopra l'80% manda l'avviso (soglia in `gazzetta-disco.service`).
   Controllo a mano: `df -h /var/lib/gazzetta-archivio`.
3. **L'ultimo aggiornamento.** Lo strumento `stato_archivio` (e il comando `stato`) riportano
   `ultimo_aggiornamento`. Se la data e' vecchia di piu' di 2-3 giorni, qualcosa non funziona
   (guarda `journalctl -u gazzetta-aggiorna`). Nota: `aggiorna` esce anche con esito "ok" quando
   una fonte si ferma per un problema (lo scrive come voce `.fermato`): per questo conviene
   guardare `ultimo_aggiornamento` e non solo gli avvisi.

**Avvisi automatici.** Se un lavoro fallisce (esito diverso da 0: aggiornamento, recupero,
controllo del parser, copia, disco) parte `gazzetta-avviso@.service`, che scrive nel registro
(`journalctl -t gazzetta-archivio`). Per riceverlo sul telefono:

- Il piu' semplice e' un servizio di notifiche con indirizzo "a cui scrivere" (per esempio
  [ntfy.sh](https://ntfy.sh): scegli un nome di argomento lungo e difficile da indovinare e
  installa l'app sul telefono). L'indirizzo e' `https://ntfy.sh/IL-TUO-ARGOMENTO`.
- Mettilo in `sudo nano /etc/gazzetta-archivio/variabili.env` alla riga `AVVISO_URL=...`.
- Prova: `sudo -u gazzetta env AVVISO_URL=https://ntfy.sh/IL-TUO-ARGOMENTO /usr/local/lib/gazzetta-archivio/avviso.sh "prova"` (dovrebbe arrivare la notifica).

(L'avviso e' un messaggio di testo con il nome dell'unita': non contiene dati dell'archivio.)

---

## Backup

**Cosa fa.** Ogni giorno alle 06:30 `gazzetta-backup.timer` esegue `backup.sh`: usa il comando
`.backup` di `sqlite3` (una copia coerente anche mentre qualcuno scrive, a differenza di `cp`),
controlla che la copia sia integra, la comprime in
`/var/backups/gazzetta-archivio/archivio-AAAA-MM-GG.sqlite3.gz` e tiene le **ultime 7** (numero
cambiabile con `COPIE_DA_TENERE` nel file di configurazione). Il collegamento `ultimo.sqlite3.gz`
punta all'ultima. Controlla lo spazio prima di cominciare: serve libero circa quanto l'archivio.

**Provalo subito** (non aspettare la notte):

```
sudo systemctl start gazzetta-backup.service
journalctl -u gazzetta-backup -n 10 --no-pager
ls -lh /var/backups/gazzetta-archivio
```

**Cosa dovresti vedere:** `Copia creata: ...` e il file nell'elenco.

**Cosa copiare FUORI dal server.** Una copia sullo stesso disco non protegge se il server si
rompe o viene cancellato. Porta fuori regolarmente (almeno una volta a settimana):

1. `/var/backups/gazzetta-archivio/ultimo.sqlite3.gz`, cioe' l'archivio (in teoria si puo'
   rifare da capo dalle fonti, ma ci vogliono settimane).
2. `/etc/gazzetta-archivio/variabili.env` (la configurazione; contiene l'email e l'eventuale
   `AVVISO_URL`).
3. Questo kit (e' nel repository GitHub, non serve copiarlo) e il tuo `Caddyfile` modificato
   (`/etc/caddy/Caddyfile`).

I certificati di Caddy **non** vanno salvati: si rifanno da soli.

Per scaricare l'archivio sul tuo computer (le copie sono leggibili da tutti gli utenti del server):

```
scp UTENTE@IP-DEL-SERVER:/var/backups/gazzetta-archivio/ultimo.sqlite3.gz .
```

Meglio ancora, attiva anche gli snapshot automatici del provider, oppure copia in un deposito
esterno (spazio di archiviazione a oggetti con `rclone`, o un secondo server): l'importante e' che
sia **un altro luogo** e che una volta provi a **ripristinare** (qui sotto).

**Attenzione ai dati personali.** Se cancelli dati su richiesta (vedi sotto), le vecchie copie di
sicurezza li contengono ancora. Tieni quindi poche copie e per poco tempo, e cancella quelle
vecchie anche fuori dal server.

### Ripristino

Da una copia `archivio-AAAA-MM-GG.sqlite3.gz` (se e' sul tuo computer, riportala sul server con
`scp archivio-AAAA-MM-GG.sqlite3.gz UTENTE@IP-DEL-SERVER:/tmp/`):

```
sudo systemctl stop gazzetta-archivio.service gazzetta-aggiorna.timer gazzetta-controlla.timer gazzetta-backup.timer
sudo systemctl stop 'gazzetta-recupera@*.timer'
sudo systemctl stop gazzetta-aggiorna.service 'gazzetta-recupera@*.service'
sudo mkdir -p /var/lib/gazzetta-archivio/vecchio
sudo sh -c 'mv /var/lib/gazzetta-archivio/archivio.sqlite3* /var/lib/gazzetta-archivio/vecchio/'
sudo sh -c 'gunzip -c /tmp/archivio-AAAA-MM-GG.sqlite3.gz > /var/lib/gazzetta-archivio/archivio.sqlite3'
sudo chown gazzetta:gazzetta-dati /var/lib/gazzetta-archivio/archivio.sqlite3
sudo chmod 0660 /var/lib/gazzetta-archivio/archivio.sqlite3
sudo gazzetta-archivio stato
```

**Cosa dovresti vedere:** il riquadro di `stato` con il numero di atti previsto. Se e' giusto,
riaccendi tutto (stesso comando del passo 12) e solo dopo cancella `/var/lib/gazzetta-archivio/vecchio`.
Se le versioni del programma sono diverse (schema vecchio), `stato` aggiorna lo schema da solo.

---

## Aggiornare il programma a una versione nuova

Fallo quando esce una nuova versione (leggi il `CHANGELOG.md` per vedere cosa cambia). Prima fai
una copia (`sudo systemctl start gazzetta-backup.service`). Poi, **da GitHub** (oggi):

```
sudo uv pip install --python /opt/gazzetta-mcp/venv/bin/python --upgrade --reinstall-package gazzetta-mcp "git+https://github.com/GiovannaFilippini/gazzetta-mcp.git"
```

oppure **da PyPI**: `sudo uv pip install --python /opt/gazzetta-mcp/venv/bin/python --upgrade gazzetta-mcp`.

Se la nuova versione cambia lo schema dell'archivio, il servizio in sola lettura rifiuta di
partire finche' lo schema non e' aggiornato (lo dice nel registro). Il comando `stato` lo
aggiorna:

```
sudo gazzetta-archivio stato
sudo systemctl restart gazzetta-archivio.service
systemctl is-active gazzetta-archivio.service
```

**Cosa dovresti vedere:** `active`. Se i file del kit (cartella `deploy/`) sono cambiati,
riesegui anche i comandi di copia del passo 9 e `sudo systemctl daemon-reload`, **senza**
sovrascrivere il tuo `variabili.env` (lascia stare la riga che lo copia) e il tuo `Caddyfile`.
Se non funziona, torna alla versione precedente: installa quella (`...@VECCHIO-TAG`) e se serve
ripristina la copia.

---

## Come fermare tutto

Solo il servizio pubblico (i lavori notturni continuano):

```
sudo systemctl stop gazzetta-archivio.service
```

Fermare tutto (servizio, lavori, proxy):

```
sudo systemctl stop gazzetta-archivio.service gazzetta-aggiorna.timer gazzetta-controlla.timer gazzetta-backup.timer gazzetta-disco.timer
sudo systemctl stop 'gazzetta-recupera@*.timer'
sudo systemctl stop gazzetta-aggiorna.service 'gazzetta-recupera@*.service' gazzetta-controlla.service
sudo systemctl stop caddy
```

**Cosa dovresti vedere:** `systemctl list-timers 'gazzetta-*'` non elenca piu' nulla, e il
`curl` del passo 13 non risponde. Per riaccendere, ripeti i comandi `enable --now` del passo 12.

Per dismettere il servizio: scarica prima l'ultima copia (vedi Backup), poi elimina il server dal
pannello del provider e cancella i record DNS. Vale anche per lo snapshot del provider e per le
copie esterne.

---

## Cancellare dati su richiesta

Se qualcuno chiede la rimozione di un testo che contiene suoi dati personali (decisione 090,
sezione "Dati personali"), serve una procedura di rimozione. Il comando **`rimuovi`** di
`python -m gazzetta_mcp.archivio` e' **previsto** (in arrivo in un altro lavoro): non e' ancora
disponibile e qui non se ne descrivono le opzioni. Quando sara' pronto, l'uso a mano sara' del
tipo `sudo gazzetta-archivio rimuovi ...` (il comando `gazzetta-archivio` di questo kit passa gli
argomenti cosi' come li riceve).

Quello che questo kit gia' ti ricorda di fare, qualunque sia il comando:

- cancellare l'atto dall'archivio **e** impedire che il recupero lo riscarichi (dettaglio di
  `rimuovi`, da leggere nella sua guida quando uscira');
- eliminare le vecchie copie di sicurezza che lo contengono, sul server e fuori;
- tenere un registro minimo (data, richiesta, esito) senza copiare il dato che si cancella;
- rispondere alla persona entro i tempi di legge (questione legale, non tecnica: se non sai
  come, chiedi consiglio prima di aprire al pubblico).

---

## Perche' due utenti e un gruppo

- `gazzetta` esegue i lavori che **scrivono** (aggiorna, recupera, controlla, copia).
- `gazzetta-web` esegue il servizio che **risponde al pubblico**. E' l'unico in contatto con
  Internet (tramite Caddy), quindi e' quello che ha meno poteri: non puo' modificare il programma,
  non vede `/home`, `/root` e le copie, e non ha una shell.
- Entrambi sono nel gruppo `gazzetta-dati` e tutte le unita' usano `UMask=0007` (con la cartella
  `2770`): i file creati da uno sono scrivibili dall'altro.

Il motivo e' la modalita' **WAL** di SQLite (usata dall'archivio): per leggere, anche in sola
lettura, SQLite deve poter creare/scrivere due file di appoggio (`-wal` e `-shm`) accanto al
database. Quindi il servizio non puo' avere la cartella dati in sola lettura (`ReadOnlyPaths=`
farebbe fallire le letture quando il file di appoggio manca). Che non possa scrivere davvero
nell'archivio e' garantito altrove: il programma lo apre con `mode=ro` e `query_only`, ed e'
verificato dai test del progetto. Il gruppo comune serve perche' se uno dei due ricrea un file
d'appoggio l'altro possa comunque usarlo.

Rimane scrivibile da `gazzetta-web` la sola cartella dati (e nient'altro nel disco: il resto e'
sola lettura per `ProtectSystem=strict`).

---

## Se qualcosa non va

Il primo posto dove guardare e' il registro del servizio che sospetti:

```
journalctl -u gazzetta-archivio -n 50 --no-pager
journalctl -u gazzetta-aggiorna -n 50 --no-pager
journalctl -u caddy -n 50 --no-pager
```

| Sintomo | Causa probabile | Cosa fare |
|---|---|---|
| `gazzetta-archivio.service` "condition failed" | Il file dell'archivio non c'e' ancora | Esegui `sudo gazzetta-archivio aggiorna` (passo 12) |
| Il servizio non parte e parla di "schema" | Versione del programma diversa da quella del file | `sudo gazzetta-archivio stato`, poi `sudo systemctl restart gazzetta-archivio` |
| Il servizio parte e si ferma subito con errore di sistema/permesso | Un'opzione di sicurezza troppo severa per la tua macchina (il kit non e' stato provato su tutte) | Guarda `journalctl`; come prova, commenta con `#` la riga `SystemCallFilter=@system-service` nel file in `/etc/systemd/system/`, poi `sudo systemctl daemon-reload` e riavvia. Riferisci il problema |
| Errore di certificato | Il DNS non punta al server o 80/443 sono chiuse | `nslookup` (passo 10), `sudo ufw status`, firewall del provider; poi `sudo systemctl reload caddy` |
| `429` anche per te appena avviato | Il proxy non sovrascrive `X-Forwarded-For` e il servizio vede un solo indirizzo | Controlla che nel `Caddyfile` ci sia `header_up X-Forwarded-For {remote_host}` e che il servizio abbia `--trust-proxy` |
| `uv: command not found` | Il comando di installazione non ha messo `uv` in `/usr/local/bin` | `ls /usr/local/bin/uv`; se manca, segui le istruzioni di <https://docs.astral.sh/uv/getting-started/installation/> |
| Un lavoro fallisce con "database is locked" | Due lavori insieme (fuori dal lucchetto) | Lancia i comandi a mano solo tramite `sudo gazzetta-archivio ...` (usa il lucchetto) |
| Tanti `.fermato` nell'output di `stato` | La fonte ha limitato o rifiutato le richieste | Aspetta; non alzare `GAZZETTA_MCP_RPS`. Se dura giorni scrivi alla fonte (contatto facoltativo, decisione 090) |

---

## Cosa NON e' stato provato

Questo kit e' stato scritto leggendo il codice e la documentazione, **senza** avviarlo su un
server reale. Da verificare alla prima installazione vera:

- L'installazione di `uv` con `UV_INSTALL_DIR`, i comandi di installazione di Caddy (cambiano nel
  tempo) e le versioni minime di `systemd`/`util-linux` (le opzioni `flock -E`, `OnCalendar` con
  intervalli `00..04`).
- Le opzioni di isolamento di systemd (`SystemCallFilter`, `ProtectSystem=strict`,
  `RestrictAddressFamilies`) con Python e le librerie del progetto.
- Il servizio con le cartelle e i gruppi del passo 7, cioe' il comportamento SQLite-WAL con due
  utenti diversi.
- La chiamata `curl` dello strumento `stato_archivio` sul protocollo MCP.
- Quanto spazio e quanto tempo servono davvero per l'archivio completo.
