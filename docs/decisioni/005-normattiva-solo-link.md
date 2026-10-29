# 005 — Normattiva: solo collegamento nella v1

- **Contesto:** Normattiva offre dal 2026-01-01 open data CC BY 4.0 (`dati.normattiva.it`), con API e download massivo.
- **Scelta:** `rimando_normattiva` costruisce il link URN `https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:<tipo>:<data>;<numero>` senza scaricare nulla. L'import massivo e' escluso dalla v1 (regola: niente download massivi) e annotato come sviluppo possibile.
- **Alternative scartate:** usare le API open data per il testo vigente (utile ma fuori dall'ambito v1). *Aggiornamento: superata in parte dalle decisioni 072 (ricerca nell'archivio) e 110 (testo vigente di un articolo per volta); il download massivo resta escluso.*
- **Come tornare indietro / estendere:** implementare un nuovo `NormattivaLinker` in `sources/normattiva.py`; nessun altro file cambia (1-2 giorni per l'import via API).
