# 021 — Parser: selectolax (backend lexbor) e stdlib

- **Scelta:** HTML con `selectolax.lexbor` (il backend `selectolax.parser`/Modest e' deprecato e solleva `ImportError` nelle versioni recenti); RSS con `xml.etree.ElementTree` della libreria standard.
- **Errori:** `ParseError` (sottoclasse di `ValueError`) solo per il feed (vuoto, XML non valido, canale senza `/eli/gu/...`), perche' senza canale non si hanno numero e data. Sommari e atti con input vuoto o sconosciuto restituiscono modelli con campi vuoti, mai eccezioni.
- **Collegamenti:** sempre `https`; i link degli atti sono ricostruiti come `<base_url>/eli/id/AAAA/MM/GG/CODICE/SERIE`; `link_pdf` e' `<base_url>/eli/gu/AAAA/MM/GG/NUMERO/SERIE/pdf`.
- **Titolo dell'atto:** `"<tipo e data> - <oggetto>"` (ad es. `DECRETO 9 settembre 2026 - Aggiornamento ...`); l'emettitore sta in `emettitore`. Il codice finale `(26A05182)` e' tolto da riassunti e titoli.
- **Tipo provvedimento:** `detect_tipo` cerca in un elenco di tipi in maiuscolo (`parsing/tipo.py`), prima nell'ultimo segmento dopo `" - "`, poi nell'intero titolo; `None` se non riconosciuto.
- **Come tornare indietro:** i parser sono funzioni pure dietro `interfaces.Parser`; sostituire `GuParser` non tocca altro.
