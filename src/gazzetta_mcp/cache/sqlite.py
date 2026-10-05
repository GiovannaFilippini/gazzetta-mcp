"""SQLite implementation of the Cache protocol (stdlib sqlite3 + FTS5)."""

from __future__ import annotations

import re
import sqlite3
import threading
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
from types import TracebackType

from ..config import Settings
from ..models import (
    Atto,
    Feed,
    FeedItem,
    RawPage,
    SearchFilters,
    SearchHit,
    Serie,
    Sommario,
    SommarioVoce,
)

Clock = Callable[[], datetime]


class CacheError(RuntimeError):
    """The cache cannot be opened or used (e.g. SQLite built without FTS5)."""


# Each entry upgrades the schema by one version (PRAGMA user_version = index + 1).
# To change the schema, append a new script; never edit an existing one.
_MIGRATIONS: list[str] = [
    """
    CREATE TABLE http_pages (
        url TEXT PRIMARY KEY,
        content BLOB NOT NULL,
        content_type TEXT NOT NULL,
        fetched_at REAL NOT NULL
    );
    CREATE TABLE feeds (
        serie TEXT PRIMARY KEY,
        numero INTEGER NOT NULL,
        data TEXT NOT NULL,
        link TEXT NOT NULL,
        stored_at REAL NOT NULL
    );
    CREATE TABLE feed_items (
        serie TEXT NOT NULL,
        pos INTEGER NOT NULL,
        codice TEXT NOT NULL,
        item_serie TEXT NOT NULL,
        data TEXT NOT NULL,
        titolo TEXT NOT NULL,
        riassunto TEXT NOT NULL,
        link TEXT NOT NULL,
        pubblicato TEXT,
        PRIMARY KEY (serie, pos)
    );
    CREATE TABLE sommari (
        serie TEXT NOT NULL,
        data TEXT NOT NULL,
        numero INTEGER NOT NULL,
        link TEXT NOT NULL,
        link_pdf TEXT NOT NULL,
        PRIMARY KEY (data, serie)
    );
    CREATE TABLE sommario_voci (
        serie TEXT NOT NULL,
        data TEXT NOT NULL,
        pos INTEGER NOT NULL,
        codice TEXT NOT NULL,
        titolo TEXT NOT NULL,
        emettitore TEXT NOT NULL,
        rubrica TEXT NOT NULL,
        link TEXT NOT NULL,
        tipo TEXT,
        PRIMARY KEY (data, serie, pos)
    );
    CREATE TABLE atti (
        codice TEXT PRIMARY KEY,
        serie TEXT NOT NULL,
        data TEXT NOT NULL,
        titolo TEXT NOT NULL,
        emettitore TEXT NOT NULL,
        tipo TEXT,
        testo TEXT NOT NULL,
        link TEXT NOT NULL,
        numero_gu INTEGER,
        scaricato_il TEXT
    );
    -- One row per searchable item; the FTS rowid equals docs.id.
    CREATE TABLE docs (
        id INTEGER PRIMARY KEY,
        kind TEXT NOT NULL,          -- 'atto' | 'voce' | 'feed'
        codice TEXT NOT NULL,
        serie TEXT NOT NULL,
        data TEXT NOT NULL,
        tipo TEXT,
        titolo TEXT NOT NULL,
        link TEXT NOT NULL,
        UNIQUE (kind, codice)
    );
    CREATE INDEX docs_codice ON docs (codice);
    CREATE VIRTUAL TABLE docs_fts USING fts5(
        titolo, emettitore, testo,
        tokenize = 'unicode61 remove_diacritics 2'
    );
    """,
    # v2: the rubrica of a sommario entry is no longer searchable text (it only added noise).
    """
    UPDATE docs_fts SET testo = ''
    WHERE rowid IN (SELECT id FROM docs WHERE kind = 'voce');
    """,
]

_WORD = re.compile(r"\w+", re.UNICODE)


_STOPWORDS = frozenset(
    "a ad al alla alle agli ai allo con da dal dalla dalle dei del della delle degli di e ed "
    "gli i il in la le lo nel nella nelle nei negli o per su sul sulla sulle sui tra fra un "
    "uno una l d".split()
)


def _stem(word: str) -> str:
    """Crude Italian stem: drop the final vowel so singular and plural share a prefix."""
    return word[:-1] if len(word) >= 5 and word[-1] in "aeio" else word


def build_match_query(text: str, *, any_word: bool = False) -> str | None:
    """Turn free user text into a safe FTS5 query.

    Every word is quoted (so operators such as AND/OR/NEAR are plain terms); Italian stopwords
    are dropped and longer words become prefixes of their stem (``acquisto`` also finds
    ``acquisti``). Words are ANDed, or ORed with ``any_word``. Returns None if empty.
    """
    words = [w.lower() for w in _WORD.findall(text)]
    if not words:
        return None
    kept = [w for w in words if w not in _STOPWORDS] or words
    terms = [f'"{_stem(w)}"*' if _stem(w) != w else f'"{w}"' for w in kept]
    return (" OR " if any_word else " ").join(terms)


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _ts(dt: datetime) -> float:
    return _utc(dt).timestamp()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _opt_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class SqliteCache:
    """Cache backed by one SQLite connection guarded by a lock (safe from asyncio threads)."""

    def __init__(self, path: str | Path, *, clock: Clock | None = None) -> None:
        self._clock: Clock = clock or _now_utc
        self._lock = threading.RLock()
        target = str(path)
        if target != ":memory:":
            file = Path(target).expanduser()
            file.parent.mkdir(parents=True, exist_ok=True)
            target = str(file)
        self._conn = sqlite3.connect(target, check_same_thread=False)
        try:
            self._conn.row_factory = sqlite3.Row
            self._check_fts5()
            if target != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL")
            self._migrate()
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_settings(cls, settings: Settings, *, clock: Clock | None = None) -> SqliteCache:
        return cls(settings.cache_path, clock=clock)

    # -- lifecycle -------------------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> SqliteCache:  # noqa: PYI034 (typing.Self needs Python 3.11)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _check_fts5(self) -> None:
        try:
            self._conn.execute("CREATE VIRTUAL TABLE temp._fts5_probe USING fts5(x)")
            self._conn.execute("DROP TABLE temp._fts5_probe")
        except sqlite3.OperationalError as exc:
            raise CacheError(
                f"This Python's SQLite build (version {sqlite3.sqlite_version}) has no FTS5 "
                "support, which gazzetta-mcp needs for local search. Use a Python build "
                "with FTS5 enabled."
            ) from exc

    def _migrate(self) -> None:
        with self._lock:
            current = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if current > len(_MIGRATIONS):
                raise CacheError(
                    f"Cache database schema v{current} is newer than this version of "
                    f"gazzetta-mcp supports (v{len(_MIGRATIONS)}). Upgrade gazzetta-mcp or "
                    "delete the cache file."
                )
            for version in range(current, len(_MIGRATIONS)):
                script = (
                    "BEGIN;\n"
                    + _MIGRATIONS[version]
                    + f"\nPRAGMA user_version = {version + 1};\nCOMMIT;"
                )
                try:
                    self._conn.executescript(script)
                except sqlite3.Error:
                    if self._conn.in_transaction:
                        self._conn.execute("ROLLBACK")
                    raise

    @property
    def schema_version(self) -> int:
        with self._lock:
            return self._conn.execute("PRAGMA user_version").fetchone()[0]

    # -- HTTP pages ------------------------------------------------------------------------

    def get_http(self, url: str, max_age_seconds: int) -> RawPage | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT content, content_type, fetched_at FROM http_pages WHERE url = ?", (url,)
            ).fetchone()
        if row is None:
            return None
        if _ts(self._clock()) - row["fetched_at"] > max_age_seconds:
            return None
        return RawPage(
            url=url,
            content=bytes(row["content"]),
            content_type=row["content_type"],
            fetched_at=datetime.fromtimestamp(row["fetched_at"], timezone.utc),
            from_cache=True,
        )

    def put_http(self, page: RawPage) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO http_pages (url, content, content_type, fetched_at) "
                "VALUES (?, ?, ?, ?)",
                (page.url, page.content, page.content_type, _ts(page.fetched_at)),
            )

    # -- feeds -----------------------------------------------------------------------------

    def get_feed(self, serie: Serie, max_age_seconds: int) -> Feed | None:
        with self._lock:
            head = self._conn.execute(
                "SELECT * FROM feeds WHERE serie = ?", (serie.value,)
            ).fetchone()
            if head is None or _ts(self._clock()) - head["stored_at"] > max_age_seconds:
                return None
            rows = self._conn.execute(
                "SELECT * FROM feed_items WHERE serie = ? ORDER BY pos", (serie.value,)
            ).fetchall()
        items = [
            FeedItem(
                codice=r["codice"],
                serie=Serie(r["item_serie"]),
                data=date.fromisoformat(r["data"]),
                titolo=r["titolo"],
                riassunto=r["riassunto"],
                link=r["link"],
                pubblicato=_opt_dt(r["pubblicato"]),
            )
            for r in rows
        ]
        return Feed(
            serie=serie,
            numero=head["numero"],
            data=date.fromisoformat(head["data"]),
            link=head["link"],
            items=items,
        )

    def put_feed(self, feed: Feed) -> None:
        s = feed.serie.value
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO feeds (serie, numero, data, link, stored_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (s, feed.numero, feed.data.isoformat(), feed.link, _ts(self._clock())),
            )
            self._conn.execute("DELETE FROM feed_items WHERE serie = ?", (s,))
            for pos, it in enumerate(feed.items):
                self._conn.execute(
                    "INSERT INTO feed_items (serie, pos, codice, item_serie, data, titolo, "
                    "riassunto, link, pubblicato) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        s,
                        pos,
                        it.codice,
                        it.serie.value,
                        it.data.isoformat(),
                        it.titolo,
                        it.riassunto,
                        it.link,
                        it.pubblicato.isoformat() if it.pubblicato else None,
                    ),
                )
                # The search index keeps feed titles even after they leave the feed.
                self._index(
                    "feed", it.codice, it.serie, it.data, None, it.link, it.titolo, "", it.riassunto
                )

    # -- sommari ---------------------------------------------------------------------------

    def get_sommario(self, data: date, serie: Serie) -> Sommario | None:
        with self._lock:
            head = self._conn.execute(
                "SELECT * FROM sommari WHERE data = ? AND serie = ?",
                (data.isoformat(), serie.value),
            ).fetchone()
            if head is None:
                return None
            rows = self._conn.execute(
                "SELECT * FROM sommario_voci WHERE data = ? AND serie = ? ORDER BY pos",
                (data.isoformat(), serie.value),
            ).fetchall()
        voci = [
            SommarioVoce(
                codice=r["codice"],
                titolo=r["titolo"],
                emettitore=r["emettitore"],
                rubrica=r["rubrica"],
                link=r["link"],
                tipo=r["tipo"],
            )
            for r in rows
        ]
        return Sommario(
            serie=serie,
            data=data,
            numero=head["numero"],
            link=head["link"],
            link_pdf=head["link_pdf"],
            voci=voci,
        )

    def put_sommario(self, sommario: Sommario) -> None:
        d, s = sommario.data.isoformat(), sommario.serie.value
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO sommari (serie, data, numero, link, link_pdf) "
                "VALUES (?, ?, ?, ?, ?)",
                (s, d, sommario.numero, sommario.link, sommario.link_pdf),
            )
            self._conn.execute("DELETE FROM sommario_voci WHERE data = ? AND serie = ?", (d, s))
            for pos, v in enumerate(sommario.voci):
                self._conn.execute(
                    "INSERT INTO sommario_voci (serie, data, pos, codice, titolo, emettitore, "
                    "rubrica, link, tipo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (s, d, pos, v.codice, v.titolo, v.emettitore, v.rubrica, v.link, v.tipo),
                )
                self._index(
                    "voce",
                    v.codice,
                    sommario.serie,
                    sommario.data,
                    v.tipo,
                    v.link,
                    v.titolo,
                    v.emettitore,
                    "",
                )

    # -- atti ------------------------------------------------------------------------------

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
            scaricato_il=_opt_dt(r["scaricato_il"]),
        )

    def put_atto(self, atto: Atto) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO atti (codice, serie, data, titolo, emettitore, tipo, "
                "testo, link, numero_gu, scaricato_il) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    atto.codice,
                    atto.serie.value,
                    atto.data.isoformat(),
                    atto.titolo,
                    atto.emettitore,
                    atto.tipo,
                    atto.testo,
                    atto.link,
                    atto.numero_gu,
                    atto.scaricato_il.isoformat() if atto.scaricato_il else None,
                ),
            )
            self._index(
                "atto",
                atto.codice,
                atto.serie,
                atto.data,
                atto.tipo,
                atto.link,
                atto.titolo,
                atto.emettitore,
                atto.testo,
            )

    def find_codice(self, codice: str) -> tuple[Serie, date] | None:
        """Series and date of an editorial code seen in any cached feed, sommario or act."""
        with self._lock:
            r = self._conn.execute(
                "SELECT serie, data FROM docs WHERE codice = ? "
                "ORDER BY CASE kind WHEN 'atto' THEN 0 WHEN 'voce' THEN 1 ELSE 2 END LIMIT 1",
                (codice,),
            ).fetchone()
        if r is None:
            return None
        return Serie(r["serie"]), date.fromisoformat(r["data"])

    # -- search ----------------------------------------------------------------------------

    def _index(
        self,
        kind: str,
        codice: str,
        serie: Serie,
        data: date,
        tipo: str | None,
        link: str,
        titolo: str,
        emettitore: str,
        testo: str,
    ) -> None:
        """Upsert one searchable row. Must run inside a transaction."""
        row = self._conn.execute(
            "SELECT id FROM docs WHERE kind = ? AND codice = ?", (kind, codice)
        ).fetchone()
        if row is None:
            cur = self._conn.execute(
                "INSERT INTO docs (kind, codice, serie, data, tipo, titolo, link) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (kind, codice, serie.value, data.isoformat(), tipo, titolo, link),
            )
            doc_id = cur.lastrowid
        else:
            doc_id = row["id"]
            self._conn.execute(
                "UPDATE docs SET serie = ?, data = ?, tipo = ?, titolo = ?, link = ? WHERE id = ?",
                (serie.value, data.isoformat(), tipo, titolo, link, doc_id),
            )
            self._conn.execute("DELETE FROM docs_fts WHERE rowid = ?", (doc_id,))
        self._conn.execute(
            "INSERT INTO docs_fts (rowid, titolo, emettitore, testo) VALUES (?, ?, ?, ?)",
            (doc_id, titolo, emettitore, testo),
        )

    def search(self, testo: str, filtri: SearchFilters) -> list[SearchHit]:
        """Full text search over everything cached. One hit per act (full text wins).

        Tries every word first; when that finds nothing falls back to any word (best first).
        """
        hits = self._search(build_match_query(testo), filtri)
        if not hits:
            hits = self._search(build_match_query(testo, any_word=True), filtri)
        return hits

    def _search(self, match: str | None, filtri: SearchFilters) -> list[SearchHit]:
        if match is None or filtri.limite <= 0:
            return []
        where = ["docs_fts MATCH ?"]
        params: list[object] = [match]
        if filtri.serie is not None:
            where.append("d.serie = ?")
            params.append(filtri.serie.value)
        if filtri.tipo is not None:
            where.append("d.tipo = ? COLLATE NOCASE")
            params.append(filtri.tipo)
        if filtri.dal is not None:
            where.append("d.data >= ?")
            params.append(filtri.dal.isoformat())
        if filtri.al is not None:
            where.append("d.data <= ?")
            params.append(filtri.al.isoformat())
        # Only constant fragments are interpolated below; every value is a bound parameter.
        sql = f"""
            WITH m AS (
                SELECT d.codice, d.kind, d.serie, d.data, d.titolo, d.link,
                       bm25(docs_fts, 4.0, 1.0, 1.0) AS score,
                       snippet(docs_fts, -1, '[', ']', '...', 24) AS snip
                FROM docs_fts JOIN docs d ON d.id = docs_fts.rowid
                WHERE {" AND ".join(where)}
            ), r AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY codice
                    ORDER BY CASE kind WHEN 'atto' THEN 0 WHEN 'voce' THEN 1 ELSE 2 END, score
                ) AS rn FROM m
            )
            SELECT * FROM r WHERE rn = 1 ORDER BY score, data DESC, codice LIMIT ?
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
            )
            for r in rows
        ]

    # -- maintenance -----------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        """Row counts per table (search_entries = items in the full text index)."""
        tables = {
            "http_pages": "http_pages",
            "feeds": "feeds",
            "feed_items": "feed_items",
            "sommari": "sommari",
            "sommario_voci": "sommario_voci",
            "atti": "atti",
            "search_entries": "docs",
        }
        with self._lock:
            return {
                name: self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for name, table in tables.items()
            }

    def clear(self) -> None:
        """Delete all cached data, keeping the schema."""
        tables = (
            "http_pages",
            "feeds",
            "feed_items",
            "sommari",
            "sommario_voci",
            "atti",
            "docs",
            "docs_fts",
        )
        with self._lock, self._conn:
            for table in tables:
                self._conn.execute(f"DELETE FROM {table}")
