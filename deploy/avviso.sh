#!/bin/sh
# Segnala un problema: lo scrive nel registro di sistema (journalctl) e, se in
# /etc/gazzetta-archivio/variabili.env c'e' AVVISO_URL, lo manda anche li' (richiesta POST con il
# testo nel corpo: va bene per ntfy.sh e per servizi simili).
# Uso: avviso.sh "testo del messaggio"
# Installato in /usr/local/lib/gazzetta-archivio/avviso.sh.

set -u
MESSAGGIO="${1:-Problema non specificato}"

logger -t gazzetta-archivio -p user.crit -- "$MESSAGGIO" 2>/dev/null || echo "$MESSAGGIO" >&2

if [ -n "${AVVISO_URL:-}" ]; then
    # Un avviso che non parte non deve far fallire altro: l'esito resta nel registro.
    curl -fsS --max-time 20 -d "$MESSAGGIO" "$AVVISO_URL" >/dev/null \
        || logger -t gazzetta-archivio -p user.err -- "Invio dell'avviso a AVVISO_URL non riuscito" 2>/dev/null \
        || true
fi
exit 0
