from __future__ import annotations

import contextlib
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
    last_access_time: float
    size: int


class SqliteStorage(BaseStorage):
    """SQLite-backed storage.

    Keys are stored as-is (no sharding, no path-safety validation -
    a key is just a SQL parameter here, not a filesystem path
    component). Values are stored as raw bytes; this class has no
    opinion about JSON. Encode with foundation.jsonlib (or anything
    else) before calling set(), and decode after get() - the same
    way callers would encode/decode before/after DiskStorage.

    Schema note: CREATE TABLE IF NOT EXISTS means an existing
    database file created before last_access_time/size existed won't
    be migrated automatically - opening one will fail on the first
    write, since those columns are NOT NULL with no default. No
    migration path is provided (pre-1.0, no persisted-data
    compatibility guarantee yet).
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
            "modified_at REAL NOT NULL, "
            "last_access_time REAL NOT NULL, "
            "size INTEGER NOT NULL"
            ")"
        )

    def set(self, key: str, value: bytes) -> None:
        # last_access_time is seeded to the write time - an entry
        # that's never been read yet has no more meaningful "last
        # accessed" value than "when it was written".
        now = now_utc_ts()

        self._conn.execute(
            f"INSERT INTO {_TABLE} "
            "(key, value, modified_at, last_access_time, size) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET "
            "value = excluded.value, "
            "modified_at = excluded.modified_at, "
            "last_access_time = excluded.last_access_time, "
            "size = excluded.size",
            (key, value, now, now, len(value)),
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
            f"SELECT modified_at, last_access_time, size FROM {_TABLE} WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            raise EntryNotFoundError(key)

        return SqliteStorageEntryMetadata(
            key=key, modified_at=row[0], last_access_time=row[1], size=row[2]
        )

    def get_and_touch(self, key: str) -> tuple[bytes, SqliteStorageEntryMetadata]:
        """Read a value and record the access, atomically - a single
        UPDATE ... RETURNING statement, protected by SQLite's own
        locking against other connections.
        """
        row = self._conn.execute(
            f"UPDATE {_TABLE} SET last_access_time = ? WHERE key = ? "
            "RETURNING value, modified_at, last_access_time, size",
            (now_utc_ts(), key),
        ).fetchone()
        if row is None:
            raise EntryNotFoundError(key)

        value, modified_at, last_access_time, size = row
        return bytes(value), SqliteStorageEntryMetadata(
            key=key,
            modified_at=modified_at,
            last_access_time=last_access_time,
            size=size,
        )

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

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        """Cross-process mutual exclusion via a real SQLite write
        transaction. BEGIN IMMEDIATE acquires SQLite's reserved lock
        immediately (rather than deferring until the first write),
        so a concurrent connection attempting the same is blocked
        for the duration - exactly the exclusion Cache.prune()'s
        scan-decide-evict sequence needs.

        isolation_level=None (autocommit) is temporarily overridden
        by this explicit BEGIN/COMMIT pair - normal operations
        outside this context manager are unaffected.
        """
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")
