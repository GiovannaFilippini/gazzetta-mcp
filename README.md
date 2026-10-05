# gazzetta-mcp

Unofficial, local [MCP](https://modelcontextprotocol.io) server to consult and search the
Italian *Gazzetta Ufficiale della Repubblica Italiana*. Free, open source (MIT).

> **Status: pre-release.** The package is **not yet published on PyPI**. Install commands below
> that use PyPI work only once it is published; see "From source" for what works today.

English | [Italiano](#italiano)

## Disclaimer

**This project is NOT an official publication and is not affiliated with the Gazzetta Ufficiale
or the Istituto Poligrafico e Zecca dello Stato.** The texts it returns are **not authentic**
and are provided **free of charge**. The only definitive text is the one published in the
Gazzetta Ufficiale in print, which prevails in case of discrepancy. Every response includes the
source and the official link; always check the official text before relying on it.

Reference wording from the source site: *"L'unico testo definitivo e' quello pubblicato sulla
Gazzetta Ufficiale a mezzo stampa, che prevale in caso di discordanza. La riproduzione dei testi
forniti nel formato elettronico e' consentita purche' venga menzionata la fonte, il carattere non
autentico e gratuito."*

## Usage policy

- Requests are made **on demand only**, when you or your assistant ask for something.
- **No bulk download** and no mirroring of the site.
- Results are kept in a **local cache** (SQLite) on your machine.
- Outgoing requests are **rate limited** (default 1 per second).
- Requests carry an **identifying User-Agent** (`gazzetta-mcp/<version> (unofficial open source client)`).

Please keep these defaults respectful of the source. See [docs/fonti.md](docs/fonti.md).

## Tools

| Tool | Parameters | What it does |
|---|---|---|
| `ultime_pubblicazioni` | `serie`, `giorni` | Latest publications of a series (SG, S1-S5, P2) over the last N days |
| `sommario` | `data`, `serie` | Table of contents of the issue of a given date and series |
| `leggi_atto` | `codice`, `data`, `serie`, `offset` | Text of an act from its editorial code (e.g. `26A05182`) |
| `cerca_concorsi` | `parole_chiave`, `regione` | Search public competitions (4th series) by keywords and region |
| `rimando_normattiva` | `atto` | Builds the permanent Normattiva link for an act (link only, no download) |
| `cerca` | `testo`, `serie`, `tipo`, `dal`, `al`, `limite` | Full-text search over the locally cached content, with filters |

Series codes: `SG` Serie Generale, `S1` Corte Costituzionale, `S2` Unione Europea, `S3` Regioni,
`S4` Concorsi ed esami, `S5` Contratti pubblici, `P2` Parte II.

## Install

Requires Python 3.10+. Once published on PyPI:

```bash
uvx gazzetta-mcp
# or
pip install gazzetta-mcp
```

### From source (works today)

The repository is currently **private**, so this needs access to it (and will work for everyone
once it is public). Replace `<owner>` with the repository owner:

```bash
uvx --from git+https://github.com/<owner>/gazzetta-mcp gazzetta-mcp
```

## Configure your MCP client

**Claude Code**

```bash
claude mcp add gazzetta -- uvx gazzetta-mcp
```

**Claude Desktop** (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "gazzetta": {
      "command": "uvx",
      "args": ["gazzetta-mcp"]
    }
  }
}
```

**Generic stdio client**: run the command `gazzetta-mcp` (or `uvx gazzetta-mcp`) and speak MCP
over stdin/stdout.

To use the from-source variant, replace the command/args with
`uvx --from git+https://github.com/<owner>/gazzetta-mcp gazzetta-mcp`.

## Configuration

All settings are environment variables, read in `src/gazzetta_mcp/config.py`.

| Variable | Default | Meaning |
|---|---|---|
| `GAZZETTA_MCP_GU_BASE_URL` | `https://www.gazzettaufficiale.it` | Base URL of the Gazzetta Ufficiale site |
| `GAZZETTA_MCP_NORMATTIVA_BASE_URL` | `https://www.normattiva.it` | Base URL used for Normattiva links |
| `GAZZETTA_MCP_RPS` | `1.0` | Maximum requests per second |
| `GAZZETTA_MCP_TIMEOUT` | `20.0` | HTTP timeout in seconds |
| `GAZZETTA_MCP_CACHE_PATH` | `<cache dir>/gazzetta-mcp/cache.sqlite3` | SQLite cache file (`LOCALAPPDATA`, else `XDG_CACHE_HOME`, else `~/.cache`) |
| `GAZZETTA_MCP_FEED_TTL` | `900` | Feed cache lifetime in seconds |
| `GAZZETTA_MCP_USER_AGENT` | `gazzetta-mcp/<version> (unofficial open source client)` | User-Agent sent with requests |

## Development

```bash
uv sync
uv run pytest            # no network needed
uv run ruff check .
uv run pytest --live     # also runs tests that call the real sites (use sparingly)
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [docs/piano.md](docs/piano.md) and
[docs/decisioni](docs/decisioni).

## License

[MIT](LICENSE). The license covers the code only; the texts remain subject to the rules of their
sources (see [docs/fonti.md](docs/fonti.md)).

---

## Italiano

Server [MCP](https://modelcontextprotocol.io) locale, **non ufficiale**, per consultare e cercare
nella *Gazzetta Ufficiale della Repubblica Italiana*. Gratuito e open source (licenza MIT).

> **Stato: pre-release.** Il pacchetto **non e' ancora pubblicato su PyPI**: i comandi di
> installazione da PyPI funzioneranno solo dopo la pubblicazione. Vedi "Da sorgente".

### Avvertenza

**Questo progetto NON e' una pubblicazione ufficiale e non e' affiliato alla Gazzetta Ufficiale
ne' all'Istituto Poligrafico e Zecca dello Stato.** I testi restituiti hanno **carattere non
autentico** e sono forniti **gratuitamente**. L'unico testo definitivo e' quello pubblicato sulla
Gazzetta Ufficiale a mezzo stampa, che prevale in caso di discordanza. Ogni risposta riporta la
fonte e il link ufficiale: verifica sempre il testo ufficiale prima di farci affidamento.

### Regole d'uso

- Le richieste partono **solo su richiesta** dell'utente.
- **Nessun download massivo**, nessuna copia del sito.
- I risultati restano in una **cache locale** (SQLite) sul tuo computer.
- Le richieste in uscita hanno un **limite di frequenza** (predefinito: 1 al secondo).
- Le richieste usano uno **user-agent identificativo**.

### Strumenti

| Strumento | Parametri | Cosa fa |
|---|---|---|
| `ultime_pubblicazioni` | `serie`, `giorni` | Ultime pubblicazioni di una serie negli ultimi N giorni |
| `sommario` | `data`, `serie` | Sommario del numero di una data e serie |
| `leggi_atto` | `codice`, `data`, `serie`, `offset` | Testo di un atto dal codice redazionale (es. `26A05182`) |
| `cerca_concorsi` | `parole_chiave`, `regione` | Cerca concorsi (4a serie) per parole chiave e regione |
| `rimando_normattiva` | `atto` | Costruisce il link permanente a Normattiva (solo link) |
| `cerca` | `testo`, `serie`, `tipo`, `dal`, `al`, `limite` | Ricerca nel testo dei contenuti in cache locale, con filtri |

Esempi di richieste in linguaggio naturale: [docs/uso.md](docs/uso.md).

### Installazione

Serve Python 3.10+. Dopo la pubblicazione su PyPI:

```bash
uvx gazzetta-mcp
# oppure
pip install gazzetta-mcp
```

**Da sorgente** (funziona oggi; il repository e' al momento **privato**, serve l'accesso;
sostituisci `<owner>` con il proprietario del repository):

```bash
uvx --from git+https://github.com/<owner>/gazzetta-mcp gazzetta-mcp
```

### Configurazione del client MCP

- Claude Code: `claude mcp add gazzetta -- uvx gazzetta-mcp`
- Claude Desktop: aggiungi a `claude_desktop_config.json` il blocco `mcpServers` mostrato sopra.
- Altri client: avvia `gazzetta-mcp` come server stdio.

Le variabili d'ambiente `GAZZETTA_MCP_*` sono descritte nella tabella "Configuration" sopra.

### Sviluppo

```bash
uv sync
uv run pytest          # senza rete
uv run ruff check .
uv run pytest --live   # include i test sui siti reali
```

Vedi [CONTRIBUTING.md](CONTRIBUTING.md). Licenza: [MIT](LICENSE) (vale per il codice; i testi
restano soggetti alle regole delle fonti, vedi [docs/fonti.md](docs/fonti.md)).
