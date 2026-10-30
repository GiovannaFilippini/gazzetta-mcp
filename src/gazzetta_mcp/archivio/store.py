"""SQLite store of the central archive. Separate file from the local cache of the client.

Acts are immutable once published: ``put_atto`` never overwrites an existing act. Every method is
safe to call from several threads. The schema changes only by appending to ``_MIGRATIONS``.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from types import TracebackType

from ..cache.sqlite import build_match_query
from ..models import Atto, SearchFilters, SearchHit, Serie
from .tipi import ARCHI_TIPI, FONTI, Arco, NumeroDaFare

STATI_NUMERO = ("da_fare", "fatto", "errore", "vuoto")  # "vuoto": issue exists but has no acts


class ArchiveError(RuntimeError):
    """The archive database cannot be used."""


_MIGRATIONS = [
    # v1
    """
    CREATE TABLE atti (
        id INTEGER PRIMARY KEY,          -- also the rowid of atti_fts
        codice TEXT NOT NULL UNIQUE,
        fonte TEXT NOT NULL,             -- 'gu' | 'normattiva'
        serie TEXT NOT NULL,
        data TEXT NOT NULL,
        titolo TEXT NOT NULL,
        emettitore TEXT NOT NULL,
        tipo TEXT,
        testo TEXT NOT NULL,
        link TEXT NOT NULL,
        numero_gu INTEGER,
        urn TEXT,                        -- shared key between the two sources, when known
        archiviato_il TEXT NOT NULL
    );
    CREATE INDEX atti_data ON atti (data);
    CREATE INDEX atti_urn ON atti (urn);
    CREATE VIRTUAL TABLE atti_fts USING fts5(
        titolo, emettitore, testo,
        tokenize = 'unicode61 remove_diacritics 2'
    );
    -- Work queue of the backward recovery: one row per issue (serie + day).
    CREATE TABLE numeri (
        serie TEXT NOT NULL,
        data TEXT NOT NULL,
        numero INTEGER,
        stato TEXT NOT NULL DEFAULT 'da_fare',
        tentativi INTEGER NOT NULL DEFAULT 0,
        ultimo_errore TEXT,
        aggiornato_il TEXT NOT NULL,
        PRIMARY KEY (serie, data)
    );
    CREATE INDEX numeri_coda ON numeri (stato, data);
    -- Typed relations between acts. Endpoints may refer to acts not archived (yet).
    CREATE TABLE archi (
        da TEXT NOT NULL,
        a TEXT NOT NULL,
        tipo TEXT NOT NULL,
        fonte TEXT NOT NULL,
        PRIMARY KEY (da, a, tipo, fonte)
    );
    CREATE INDEX archi_a ON archi (a);
    -- Free key/value notes of the jobs (cursors, last run, parser check result).
    CREATE TABLE stato (
        chiave TEXT PRIMARY KEY,
        valore TEXT NOT NULL,
        aggiornato_il TEXT NOT NULL
    );
    """,
    # v2: an act taken from Normattiva holds only its first article; the GU copy completes it.
    """
    ALTER TABLE atti ADD COLUMN testo_completo INTEGER NOT NULL DEFAULT 1;
    """,
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArchiveStore:
    def __init__(self, path: str | Path) -> None:
        self._lock = threading.RLock()
        target = str(path)
        if target != ":memory:":
            file = Path(target).expanduser()
            file.parent.mkdir(parents=True, exist_ok=True)
            target = str(file)
        try:
            self._conn = sqlite3.connect(target, check_same_thread=False)
        except sqlite3.Error as exc:
            raise ArchiveError(f"Cannot open the archive {target}: {exc}") from exc
        try:
            self._conn.row_factory = sqlite3.Row
            if target != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL")
            self._migrate()
        except sqlite3.Error as exc:  # not a database, corrupt, locked...
            self._conn.close()
            raise ArchiveError(f"Cannot use the archive {target}: {exc}") from exc
        except Exception:
            self._conn.close()
            raise

    def _migrate(self) -> None:
        with self._lock:
            current = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if current > len(_MIGRATIONS):
                raise ArchiveError(
                    f"Archive schema v{current} is newer than this version of gazzetta-mcp."
                )
            for version in range(current, len(_MIGRATIONS)):
                try:
                    self._conn.executescript(
                        f"BEGIN;{_MIGRATIONS[version]}PRAGMA user_version = {version + 1};COMMIT;"
                    )
                except sqlite3.Error as exc:
                    self._conn.rollback()
                    raise ArchiveError(f"Archive migration v{version + 1} failed: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> ArchiveStore:  # noqa: PYI034 (typing.Self needs Python 3.11)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- acts -------------------------------------------------------------------------------

    def has_atto(self, codice: str) -> bool:
        with self._lock:
            return (
                self._conn.execute("SELECT 1 FROM atti WHERE codice = ?", (codice,)).fetchone()
                is not None
            )

    def put_atto(
        self, atto: Atto, *, fonte: str, urn: str | None = None, completo: bool = True
    ) -> bool:
        """Store an act. Returns False (and changes nothing) if the code is already archived.

        ``completo=False`` marks a partial text (e.g. only the first article from Normattiva):
        it can later be replaced with ``sostituisci_atto``.
        """
        if fonte not in FONTI:
            raise ValueError(f"fonte must be one of {FONTI}, got {fonte!r}")
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO atti (codice, fonte, serie, data, titolo, emettitore, tipo,"
                " testo, link, numero_gu, urn, archiviato_il, testo_completo)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    atto.codice,
                    fonte,
                    atto.serie.value,
                    atto.data.isoformat(),
                    atto.titolo,
                    atto.emettitore,
                    atto.tipo,
                    atto.testo,
                    atto.link,
                    atto.numero_gu,
                    urn,
                    _now(),
                    int(completo),
                ),
            )
            if cur.rowcount == 0:
                return False
            self._conn.execute(
                "INSERT INTO atti_fts (rowid, titolo, emettitore, testo) VALUES (?,?,?,?)",
                (cur.lastrowid, atto.titolo, atto.emettitore, atto.testo),
            )
            return True

    def ha_testo_completo(self, codice: str) -> bool:
        """True if the act is archived with its full text (False: absent or partial)."""
        with self._lock:
            r = self._conn.execute(
                "SELECT testo_completo, testo FROM atti WHERE codice = ?", (codice,)
            ).fetchone()
        return r is not None and bool(r["testo_completo"]) and bool(r["testo"])

    def sostituisci_atto(self, atto: Atto, *, fonte: str, completo: bool = True) -> bool:
        """Replace an archived act whose text is partial or empty. Never touches a full text.

        Returns True if the act was replaced.
        """
        if fonte not in FONTI:
            raise ValueError(f"fonte must be one of {FONTI}, got {fonte!r}")
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT id, testo_completo, testo, urn FROM atti WHERE codice = ?", (atto.codice,)
            ).fetchone()
            if row is None or (row["testo_completo"] and row["testo"]):
                return False
            self._conn.execute(
                "UPDATE atti SET fonte=?, serie=?, data=?, titolo=?, emettitore=?, tipo=?,"
                " testo=?, link=?, numero_gu=?, archiviato_il=?, testo_completo=? WHERE id=?",
                (
                    fonte,
                    atto.serie.value,
                    atto.data.isoformat(),
                    atto.titolo,
                    atto.emettitore,
                    atto.tipo,
                    atto.testo,
                    atto.link,
                    atto.numero_gu,
                    _now(),
                    int(completo),
                    row["id"],
                ),
            )
            self._conn.execute("DELETE FROM atti_fts WHERE rowid = ?", (row["id"],))
            self._conn.execute(
                "INSERT INTO atti_fts (rowid, titolo, emettitore, testo) VALUES (?,?,?,?)",
                (row["id"], atto.titolo, atto.emettitore, atto.testo),
            )
            return True

    def set_urn(self, codice: str, urn: str) -> None:
        """Record the URN of an archived act (links the GU and Normattiva copies of it)."""
        with self._lock, self._conn:
            self._conn.execute("UPDATE atti SET urn = ? WHERE codice = ?", (urn, codice))

    def get_atto(self, codice: str) -> Atto | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM atti WHERE codice = ?", (codice,)).fetchone()
        if r is None:
            return None
        return Atto(
            codice=r["codice"],
            serie=Serie(r["serie"]),
            data=date.fromisoformat(r["data"]),
            titolo=r["titolo"],
            emettitore=r["emettitore"],
            tipo=r["tipo"],
            testo=r["testo"],
            link=r["link"],
            numero_gu=r["numero_gu"],
            scaricato_il=datetime.fromisoformat(r["archiviato_il"]),
        )

    def codice_da_urn(self, urn: str) -> str | None:
        with self._lock:
            r = self._conn.execute("SELECT codice FROM atti WHERE urn = ?", (urn,)).fetchone()
        return r["codice"] if r else None

    def count_atti(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM atti").fetchone()[0]

    def search(self, testo: str, filtri: SearchFilters) -> list[SearchHit]:
        """Full text search, same rules as the local cache. Hits have ``origine='archivio'``."""
        hits = self._search(build_match_query(testo), filtri)
        if not hits:
            hits = self._search(build_match_query(testo, any_word=True), filtri)
        return hits

    def _search(self, match: str | None, filtri: SearchFilters) -> list[SearchHit]:
        if match is None or filtri.limite <= 0:
            return []
        where = ["atti_fts MATCH ?"]
        params: list[object] = [match]
        if filtri.serie is not None:
            where.append("a.serie = ?")
            params.append(filtri.serie.value)
        if filtri.tipo is not None:
            where.append("a.tipo = ? COLLATE NOCASE")
            params.append(filtri.tipo)
        if filtri.dal is not None:
            where.append("a.data >= ?")
            params.append(filtri.dal.isoformat())
        if filtri.al is not None:
            where.append("a.data <= ?")
            params.append(filtri.al.isoformat())
        # Only constant fragments are interpolated below; every value is a bound parameter.
        sql = f"""
            SELECT a.codice, a.serie, a.data, a.titolo, a.link,
                   bm25(atti_fts, 4.0, 1.0, 1.0) AS score,
                   snippet(atti_fts, -1, '[', ']', '...', 24) AS snip
            FROM atti_fts JOIN atti a ON a.id = atti_fts.rowid
            WHERE {" AND ".join(where)}
            ORDER BY score, a.data DESC, a.codice LIMIT ?
        """
        params.append(filtri.limite)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            SearchHit(
                codice=r["codice"],
                serie=Serie(r["serie"]),
                data=date.fromisoformat(r["data"]),
                titolo=r["titolo"],
                estratto=r["snip"],
                link=r["link"],
                punteggio=-float(r["score"]),
                origine="archivio",
            )
            for r in rows
        ]

    # -- work queue of the issues ----------------------------------------------------------

    def aggiungi_numeri(self, voci: Iterable[tuple[Serie, date, int | None]]) -> int:
        """Queue issues. Known ones are left alone, except that a missing number gets filled in.
        Returns how many issues were new."""
        new = 0
        with self._lock, self._conn:
            for serie, giorno, numero in voci:
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO numeri (serie, data, numero, aggiornato_il)"
                    " VALUES (?,?,?,?)",
                    (serie.value, giorno.isoformat(), numero, _now()),
                )
                new += cur.rowcount
                if cur.rowcount == 0 and numero is not None:
                    self._conn.execute(
                        "UPDATE numeri SET numero = ? WHERE serie = ? AND data = ?"
                        " AND numero IS NULL",
                        (numero, serie.value, giorno.isoformat()),
                    )
        return new

    def prossimi_numeri(
        self, serie: Serie, limite: int, *, max_tentativi: int = 5
    ) -> list[NumeroDaFare]:
        """Issues still to do, newest first (the recovery goes backward in time). Issues that
        failed are retried until they reach ``max_tentativi``."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM numeri WHERE serie = ? AND (stato = 'da_fare'"
                " OR (stato = 'errore' AND tentativi < ?)) ORDER BY data DESC LIMIT ?",
                (serie.value, max_tentativi, limite),
            ).fetchall()
        return [
            NumeroDaFare(
                serie=Serie(r["serie"]),
                data=date.fromisoformat(r["data"]),
                numero=r["numero"],
                tentativi=r["tentativi"],
            )
            for r in rows
        ]

    def segna_numero(
        self, serie: Serie, giorno: date, stato: str, errore: str | None = None
    ) -> None:
        """Set the state of an issue; a state 'errore' also counts one more attempt."""
        if stato not in STATI_NUMERO:
            raise ValueError(f"stato must be one of {STATI_NUMERO}, got {stato!r}")
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE numeri SET stato = ?, ultimo_errore = ?, aggiornato_il = ?,"
                " tentativi = tentativi + ? WHERE serie = ? AND data = ?",
                (
                    stato,
                    errore,
                    _now(),
                    1 if stato == "errore" else 0,
                    serie.value,
                    giorno.isoformat(),
                ),
            )

    def conteggio_numeri(self, serie: Serie | None = None) -> dict[str, int]:
        sql = "SELECT stato, COUNT(*) AS n FROM numeri"
        params: tuple[str, ...] = ()
        if serie is not None:
            sql += " WHERE serie = ?"
            params = (serie.value,)
        with self._lock:
            rows = self._conn.execute(sql + " GROUP BY stato", params).fetchall()
        return {r["stato"]: r["n"] for r in rows}

    # -- graph ------------------------------------------------------------------------------

    def put_archi(self, archi: Iterable[Arco]) -> int:
        """Store relations (duplicates ignored). Returns how many were new."""
        rows = []
        for arco in archi:
            if arco.tipo not in ARCHI_TIPI:
                raise ValueError(f"tipo must be one of {ARCHI_TIPI}, got {arco.tipo!r}")
            if arco.fonte not in FONTI:
                raise ValueError(f"fonte must be one of {FONTI}, got {arco.fonte!r}")
            rows.append((arco.da, arco.a, arco.tipo, arco.fonte))
        new = 0
        with self._lock, self._conn:
            for row in rows:
                new += self._conn.execute(
                    "INSERT OR IGNORE INTO archi (da, a, tipo, fonte) VALUES (?,?,?,?)", row
                ).rowcount
        return new

    def archi_di(self, codice: str, *, uscenti: bool = True) -> list[Arco]:
        """Relations starting from the act (``uscenti``) or pointing at it."""
        col, other = ("da", "a") if uscenti else ("a", "da")
        with self._lock:
            rows = self._conn.execute(
                f"SELECT da, a, tipo, fonte FROM archi WHERE {col} = ? ORDER BY {other}, tipo",
                (codice,),
            ).fetchall()
        return [Arco(r["da"], r["a"], r["tipo"], r["fonte"]) for r in rows]

    def read(self, sql: str, params: Sequence[object] = ()) -> list[sqlite3.Row]:
        """Run a read-only query (SELECT or WITH), e.g. a recursive one over ``archi``."""
        if not sql.lstrip().lower().startswith(("select", "with")):
            raise ValueError("read() only accepts SELECT or WITH queries")
        with self._lock:
            self._conn.execute("PRAGMA query_only = ON")
            try:
                return self._conn.execute(sql, params).fetchall()
            finally:
                self._conn.execute("PRAGMA query_only = OFF")

    # -- notes of the jobs ------------------------------------------------------------------

    def get_stato(self, chiave: str) -> str | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT valore FROM stato WHERE chiave = ?", (chiave,)
            ).fetchone()
        return r["valore"] if r else None

    def set_stato(self, chiave: str, valore: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO stato (chiave, valore, aggiornato_il) VALUES (?,?,?)"
                " ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore,"
                " aggiornato_il = excluded.aggiornato_il",
                (chiave, valore, _now()),
            )
