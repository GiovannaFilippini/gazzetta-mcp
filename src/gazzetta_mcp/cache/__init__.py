"""Local SQLite cache with FTS5 search."""

from .sqlite import CacheError, SqliteCache, build_match_query

__all__ = ["CacheError", "SqliteCache", "build_match_query"]
