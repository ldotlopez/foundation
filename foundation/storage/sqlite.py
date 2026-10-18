import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from ..dblib import SQLite3DB
from ..dtlib import now_utc_ts
from ._base import EntryNotFoundError
from ._maintenance import claim_maintenance, create_maintenance_clock

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SqliteStorageEntryMetadata:
    """SQLite-specific metadata for a storage entry."""

    key: str
    created_at: float
    modified_at: float
    last_access_time: float
    size: int


class SqliteStorage:
    """Values and metadata in a single SQLite table.

    Keys are SQL parameters, so any string is accepted. Values are raw
    bytes; encode and decode them in the caller.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        """Open or create the database.

        Args:
            db_path: Database file; parent directories are created. If
                omitted, an in-memory database is used and a warning is
                logged, since nothing written to it persists.
        """
        self.db_path = db_path
        if db_path is None:
            LOGGER.warning(
                "SqliteStorage created without db_path; using an "
                "in-memory database. Nothing written will persist."
            )
            target = Path(":memory:")
        else:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            target = db_path

        self._db = SQLite3DB(target, use_dict_rows=True)
        with self._db.transition() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    key TEXT PRIMARY KEY,
                    value BLOB NOT NULL,
                    created_at REAL NOT NULL,
                    modified_at REAL NOT NULL,
                    last_access_time REAL NOT NULL,
                    size INTEGER NOT NULL
                )
                """
            )
            create_maintenance_clock(cursor, now_utc_ts())

    def get(self, key: str) -> bytes:
        value, _ = self.get_with_metadata(key)
        return value

    def set(self, key: str, value: bytes) -> None:
        now = now_utc_ts()
        with self._db.transition() as cursor:
            cursor.execute(
                """
                INSERT INTO entries
                    (key, value, created_at, modified_at, last_access_time, size)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    modified_at = excluded.modified_at,
                    last_access_time = excluded.last_access_time,
                    size = excluded.size
                """,
                (key, value, now, now, now, len(value)),
            )

    def delete(self, key: str) -> None:
        with self._db.transition() as cursor:
            cursor.execute("DELETE FROM entries WHERE key = ?", (key,))

    def get_metadata(self, key: str) -> SqliteStorageEntryMetadata:
        with self._db.transition() as cursor:
            row = cursor.execute(
                """
                SELECT key, created_at, modified_at, last_access_time, size
                FROM entries WHERE key = ?
                """,
                (key,),
            ).fetchone()
        if row is None:
            raise EntryNotFoundError(key)
        return SqliteStorageEntryMetadata(**row)

    def get_with_metadata(self, key: str) -> tuple[bytes, SqliteStorageEntryMetadata]:
        with self._db.transition() as cursor:
            row = cursor.execute(
                """
                UPDATE entries SET last_access_time = ? WHERE key = ?
                RETURNING value, key, created_at, modified_at, last_access_time, size
                """,
                (now_utc_ts(), key),
            ).fetchone()
        if row is None:
            raise EntryNotFoundError(key)
        value = row.pop("value")
        return bytes(value), SqliteStorageEntryMetadata(**row)

    def iter(self) -> Iterator[str]:
        with self._db.transition() as cursor:
            rows = cursor.execute("SELECT key FROM entries ORDER BY key").fetchall()
        for row in rows:
            yield row["key"]

    def cleanup(self, *, dry_run: bool = False) -> list[str]:
        """Nothing to clean up: SQLite leaves no artifacts behind."""
        return []

    def claim_maintenance(self, interval: float) -> bool:
        with self._db.transition() as cursor:
            return claim_maintenance(cursor, interval, now_utc_ts())

    def close(self) -> None:
        self._db.close()
