#!/bin/sh
# Controlla lo spazio su disco della cartella dati. Esce con 1 (e quindi fa partire l'avviso)
# se l'uso supera SOGLIA_DISCO per cento (default 80).
# Installato in /usr/local/lib/gazzetta-archivio/disco.sh, avviato da gazzetta-disco.timer.

set -eu
CARTELLA="${CARTELLA_DATI:-/var/lib/gazzetta-archivio}"
SOGLIA="${SOGLIA_DISCO:-80}"

USO="$(df -P "$CARTELLA" | awk 'NR==2 {gsub("%","",$5); print $5}')"
echo "Disco usato: ${USO}% (soglia ${SOGLIA}%)"
if [ "$USO" -ge "$SOGLIA" ]; then
    echo "Disco quasi pieno: ${USO}% usato. Fai spazio o ingrandisci il disco." >&2
    exit 1
fi
