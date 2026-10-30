# Oracle Cloud «Always Free»: cosa cambia rispetto alla guida

Questa pagina si legge **insieme** a `README.md`. Serve per la prova a costo zero su Oracle. I passi
non nominati qui restano uguali a quelli del `README.md`.

> Tutto quello che segue e' scritto senza avere davanti lo schermo di Oracle e da fonti di terzi
> sui limiti del 2026, che a volte si contraddicono. I nomi dei menu possono essere diversi: se qualcosa
> non torna, **fermati e scrivimi cosa vedi**. Le cose da controllare per prime sono segnate con
> **[CONTROLLA]**.

## Prima: scegliere e conoscere i limiti

- **Regione:** si sceglie alla creazione dell'account e non si cambia. Per questo progetto:
  Francoforte (`eu-frankfurt-1`) o Milano (`eu-milan-1`), in Unione Europea.
- **Due tipi di macchina gratuita** **[CONTROLLA i limiti attuali nella pagina «Always Free» di Oracle]**:
  - **Ampere A1 (ARM)**: la piu' comoda (piu' memoria). Spesso risulta «esaurita»: riprova in orari diversi.
    Chiedi **1 processore e 6 GB** di memoria, bastano e restano nei limiti anche se Oracle li ha ridotti.
  - **AMD «Micro»** (`VM.Standard.E2.1.Micro`): 1 GB di memoria, funziona ma e' stretta. Se la usi,
    aggiungi un po' di «swap» (spazio di appoggio) e tieni i lotti piccoli.
- **Rischio di ritiro:** Oracle puo' ritirare una macchina gratuita **poco usata**
  (sotto il 20% di utilizzo per una settimana, secondo le fonti). Il servizio sara' spesso a riposo.
  Rimedio: passare al piano «Pay As You Go», che resta gratuito dentro i limiti Always Free ma
  **puo' addebitare la carta** se li superi. Decidiamo insieme quando vedi la macchina. Per questo
  le copie di sicurezza vanno tenute **fuori** (vedi in fondo).

## Passo 1 (creare la macchina) — cosa fare su Oracle

1. Nel pannello Oracle: menu in alto a sinistra → **Compute** → **Instances** → **Create instance**.
2. **Name:** `gazzetta-archivio`.
3. **Image:** premi *Change image* e scegli **Canonical Ubuntu 24.04** (o 22.04).
4. **Shape:** *Change shape* → *Ampere* → `VM.Standard.A1.Flex`, **1 OCPU, 6 GB**. Deve esserci
   la dicitura «Always Free-eligible». Se dice «Out of capacity», riprova piu' tardi o usa la AMD Micro.
5. **Networking:** lascia la rete nuova (VCN) che propone e assicurati che sia **«Assign a public IPv4
   address»** (indirizzo pubblico).
6. **Add SSH keys:** scegli «Upload public key» e carica la chiave pubblica fatta nel passo 2 del
   `README.md` (oppure «Generate a key pair» e **scarica subito la chiave privata**: non si puo'
   riscaricare dopo).
7. **Boot volume:** lascia il valore proposto (circa 50 GB, dentro il gratuito).
8. Premi **Create** e aspetta che lo stato sia **Running**. Annota l'**indirizzo IP pubblico**.

L'utente per entrare col SSH e' **`ubuntu`** (non `root`): `ssh ubuntu@INDIRIZZO_IP`.

## Passo 6 (firewall) — in Oracle sono DUE blocchi, non uno

1. **Nel pannello Oracle** (blocco di rete): *Networking* → *Virtual cloud networks* → la tua rete →
   la *subnet* pubblica → **Security List** → **Add Ingress Rules**: aggiungi **TCP, porta 80** e
   **TCP, porta 443**, origine `0.0.0.0/0`. La 22 c'e' gia'.
2. **Dentro la macchina** (le immagini Ubuntu di Oracle hanno regole `iptables` che rifiutano il resto).
   **Non attivare `ufw`** come scrive il `README.md`: si accavalla. Esegui invece:
   ```
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
   sudo apt-get install -y iptables-persistent
   sudo netfilter-persistent save
   ```
   Se `iptables-persistent` chiede di salvare le regole attuali, rispondi **Si'**.
   **[CONTROLLA]** con `sudo iptables -L INPUT -n --line-numbers` che le due regole stiano **prima**
   della riga `REJECT`: se il numero `6` non e' quello giusto, scrivimi l'elenco.

## Passo 10 (dominio) — senza comprare un dominio

Per il certificato HTTPS serve un nome. Gratis, per la prova, si puo' usare un sottodominio di un
servizio come **DuckDNS** **[CONTROLLA che sia ancora gratuito e attivo]**:

1. Vai su duckdns.org e accedi (con un account che hai gia', per esempio Google o GitHub).
2. Scegli un nome libero, per esempio `gazzetta-prova`: otterrai `gazzetta-prova.duckdns.org`.
3. Nella casella dell'indirizzo («current ip») scrivi l'**IP pubblico** della macchina e premi *update ip*.
4. In `deploy/Caddyfile` e nei comandi del `README.md` usa quel nome al posto di `archivio.tuodominio.it`.
5. Controlla dal tuo PC: `nslookup gazzetta-prova.duckdns.org` deve rispondere con l'IP giusto.

Il nome DuckDNS cambia se cambi macchina: va bene per la prova. Per uso stabile servira' un dominio
tuo, e allora non cambia piu' nulla per chi usa il servizio.

## Altre differenze piccole

- **Utente:** al posto di `root` o dell'utente del provider, qui e' `ubuntu`. I comandi con `sudo` del
  `README.md` valgono uguali.
- **ARM:** se un pacchetto non si installa nel passo 8, e' quasi sempre per l'architettura ARM.
  Scrivimi l'errore intero. **[CONTROLLA]** con `uv run python -c "import selectolax, httpx"` dopo l'installazione.
- **Orari:** la macchina Oracle e' in orario UTC. Gli orari dei timer nel kit sono quindi un'ora o due
  indietro rispetto all'Italia: va bene, sono corse notturne.

## Copie di sicurezza FUORI dalla macchina (obbligatorio per questa prova)

Se Oracle ritira la macchina, perdi anche le copie fatte sul server. Una volta alla settimana, dal tuo PC
con Windows (PowerShell):
```
scp ubuntu@INDIRIZZO_IP:/var/backups/gazzetta-archivio/ultimo.sqlite3.gz "$HOME\Documents\gazzetta-backup\"
```
(crea prima la cartella `Documents\gazzetta-backup`). Con quel file l'archivio si riporta su un
altro server: vedi «Ripristino» nel `README.md`.

## Cosa NON e' stato provato

Nessun passo di questa pagina e' stato eseguito su Oracle: i nomi dei menu, i limiti attuali, la
disponibilita' delle macchine ARM, le regole `iptables` delle immagini Ubuntu, l'installazione su ARM
e il funzionamento di DuckDNS con Caddy. Si prova insieme, un passo alla volta.
