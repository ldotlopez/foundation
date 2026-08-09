from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from ..dtlib import now_utc_ts
from . import BaseStorage, EntryNotFoundError, StorageEntryMetadata

LOGGER = logging.getLogger(__name__)

_TABLE = "entries"


@dataclass(frozen=True)
class SqliteStorageEntryMetadata(StorageEntryMetadata):
    """SQLite-specific metadata for a storage entry."""

    modified_at: float


class SqliteStorage(BaseStorage):
    """SQLite-backed storage.

    Keys are stored as-is (no sharding, no path-safety validation -
    a key is just a SQL parameter here, not a filesystem path
    component). Values are stored as raw bytes; this class has no
    opinion about JSON. Encode with foundation.jsonlib (or anything
    else) before calling set(), and decode after get() - the same
    way callers would encode/decode before/after DiskStorage.
    """

    def __init__(self, db_path: Path | None = None):
        """
        Args:
            db_path: Path to the SQLite database file. Parent
                directories are created if needed. If omitted, an
                in-memory database is used - convenient for tests,
                but data disappears once this instance is closed or
                garbage collected. A warning is logged in that case,
                since defaulting to in-memory is easy to hit by
                accident and silently lose everything written.
        """
        self.db_path = db_path

        if db_path is None:
            LOGGER.warning(
                "SqliteStorage created without db_path; using an "
                "in-memory database. Nothing written will persist."
            )
            target = ":memory:"
        else:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            target = str(db_path)

        # isolation_level=None -> autocommit, so every statement is
        # durable immediately and callers never need to remember to
        # commit. check_same_thread defaults to True, which as a
        # side effect enforces this project's no-concurrent-threads
        # assumption for this connection specifically - using it
        # from another thread raises rather than silently racing.
        self._conn = sqlite3.connect(target, isolation_level=None)
        self._conn.execute(
            f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
            "key TEXT PRIMARY KEY, "
            "value BLOB NOT NULL, "
            "modified_at REAL NOT NULL"
            ")"
        )

    def set(self, key: str, value: bytes) -> None:
        self._conn.execute(
            f"INSERT INTO {_TABLE} (key, value, modified_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET "
            "value = excluded.value, modified_at = excluded.modified_at",
            (key, value, now_utc_ts()),
        )

    def get(self, key: str) -> bytes:
        row = self._conn.execute(
            f"SELECT value FROM {_TABLE} WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            raise EntryNotFoundError(key)
        return bytes(row[0])

    def delete(self, key: str) -> None:
        self._conn.execute(f"DELETE FROM {_TABLE} WHERE key = ?", (key,))

    def get_metadata(self, key: str) -> SqliteStorageEntryMetadata:
        row = self._conn.execute(
            f"SELECT modified_at FROM {_TABLE} WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            raise EntryNotFoundError(key)
        return SqliteStorageEntryMetadata(key=key, modified_at=row[0])

    def iter(self) -> Iterator[str]:
        # Lazy cursor, same contract as DiskStorage.iter(): callers
        # that delete while iterating should materialize first (e.g.
        # list(storage.iter())), same as Cache.prune() already does.
        cursor = self._conn.execute(f"SELECT key FROM {_TABLE} ORDER BY key")
        for row in cursor:
            yield row[0]

    def close(self) -> None:
        """Close the underlying connection.

        Not part of BaseStorage's interface (DiskStorage has nothing
        to close), but SqliteStorage holds a real OS resource, so
        it's provided for callers who want to release it explicitly
        instead of waiting on garbage collection.
        """
        self._conn.close()
