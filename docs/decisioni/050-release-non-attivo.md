# 050 — Workflow di rilascio presente ma non attivo

- **Contesto:** il pacchetto deve poter essere pubblicato su PyPI, ma la pubblicazione e' una decisione del maintainer e non si puo' annullare (una versione su PyPI non si riusa).
- **Scelta:** `.github/workflows/release.yml` usa il trusted publishing (`pypa/gh-action-pypi-publish`, build con `uv build`, ambiente `pypi`, permesso `id-token: write`). Parte **solo** con `workflow_dispatch` e solo se l'input `confirm` vale `publish`. Nessun trigger su tag o push. Il README dichiara che il pacchetto non e' ancora pubblicato.
- **Per attivarlo (maintainer):** registrare il trusted publisher su PyPI (progetto, repository, workflow `release.yml`, ambiente `pypi`), creare l'ambiente `pypi` su GitHub, aggiornare versione e CHANGELOG, poi lanciare il workflow a mano.
- **Alternative scartate:** pubblicazione automatica su tag (rischio di rilasci involontari); token API di PyPI nei secrets (piu' rischioso del trusted publishing).
- **Come tornare indietro:** eliminare `release.yml`. Se si aggiunge un trigger su tag, registrare una nuova decisione.
