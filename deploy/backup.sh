#!/bin/sh
# Copia di sicurezza consistente dell'archivio SQLite, con rotazione semplice.
# Installato in /usr/local/lib/gazzetta-archivio/backup.sh e avviato da gazzetta-backup.timer
# (utente "gazzetta"). Si puo' lanciare anche a mano:
#   sudo -u gazzetta /usr/local/lib/gazzetta-archivio/backup.sh
#
# Attenzione: con umask 0022 le copie sono leggibili da TUTTI gli utenti locali del server e
# contengono l'intero archivio. Su un server con un solo amministratore va bene; se non e' cosi',
# restringi i permessi (umask 0027 e cartella di gruppo) o la cartella.
#
# Perche' ".backup" e non "cp": l'archivio e' in modalita' WAL e un aggiornamento puo' essere in
# corso. Copiare il file con cp puo' dare una copia rotta; il comando ".backup" di sqlite3
# produce invece una copia coerente anche mentre qualcuno scrive.
#
# Variabili (tutte facoltative):
#   GAZZETTA_MCP_ARCHIVIO_PATH  archivio da copiare (come nel resto del kit)
#   CARTELLA_COPIE              dove mettere le copie (default /var/backups/gazzetta-archivio)
#   COPIE_DA_TENERE             quante copie giornaliere tenere (default 7)

set -eu
umask 0022

ARCHIVIO="${GAZZETTA_MCP_ARCHIVIO_PATH:-/var/lib/gazzetta-archivio/archivio.sqlite3}"
CARTELLA="${CARTELLA_COPIE:-/var/backups/gazzetta-archivio}"
TENERE="${COPIE_DA_TENERE:-7}"

if [ ! -f "$ARCHIVIO" ]; then
    echo "Archivio non trovato: $ARCHIVIO" >&2
    exit 1
fi
if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "Manca il programma sqlite3 (sudo apt install sqlite3)." >&2
    exit 1
fi

mkdir -p "$CARTELLA"
OGGI="$(date +%Y-%m-%d)"
TMP="$CARTELLA/.in-corso-$OGGI.sqlite3"
FINALE="$CARTELLA/archivio-$OGGI.sqlite3.gz"
rm -f "$TMP"

# Spazio: serve circa 2,2 volte l'archivio (la copia grezza piu' quella compressa .gz, che
# per un momento stanno insieme sul disco).
DIM_KB="$(du -k "$ARCHIVIO" | cut -f1)"
LIBERO_KB="$(df -Pk "$CARTELLA" | awk 'NR==2 {print $4}')"
if [ "$LIBERO_KB" -lt "$((DIM_KB * 22 / 10))" ]; then
    echo "Spazio insufficiente per la copia (servono ~$((DIM_KB * 22 / 10)) KB, liberi ${LIBERO_KB} KB)." >&2
    exit 1
fi

# .timeout: se l'archivio e' occupato aspetta fino a 10 minuti invece di fallire subito.
sqlite3 "$ARCHIVIO" ".timeout 600000" ".backup '$TMP'"

# La copia deve essere sana, altrimenti non la teniamo.
RISULTATO="$(sqlite3 "$TMP" "PRAGMA integrity_check;")"
if [ "$RISULTATO" != "ok" ]; then
    echo "La copia non ha superato il controllo di integrita': $RISULTATO" >&2
    rm -f "$TMP"
    exit 1
fi

gzip -c "$TMP" > "$FINALE.parziale"
mv "$FINALE.parziale" "$FINALE"
rm -f "$TMP"
ln -sfn "$(basename "$FINALE")" "$CARTELLA/ultimo.sqlite3.gz"

# Rotazione: tieni le ultime $TENERE copie, cancella le piu' vecchie.
# (I nomi hanno la data, quindi l'ordine alfabetico e' l'ordine del tempo.)
ls -1 "$CARTELLA"/archivio-*.sqlite3.gz 2>/dev/null | sort -r | tail -n +"$((TENERE + 1))" | while read -r vecchia; do
    rm -f "$vecchia"
done

echo "Copia creata: $FINALE"
