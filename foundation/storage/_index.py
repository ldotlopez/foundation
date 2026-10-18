from dataclasses import dataclass
from pathlib import Path

from ..dblib import SQLite3DB
from ..dtlib import now_utc_ts
from ._maintenance import claim_cleanup, create_cleanup_clock


@dataclass(frozen=True, slots=True)
class IndexedMetadata:
    key: str
    created_at: float
    modified_at: float
    last_access_time: float
    size: int


class MetadataIndex:
    """SQLite index mapping keys to backing object ids and their metadata."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._db = SQLite3DB(db_path, use_dict_rows=True)
        with self._db.transition() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    key TEXT PRIMARY KEY,
                    object_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    modified_at REAL NOT NULL,
                    last_access_time REAL NOT NULL,
                    size INTEGER NOT NULL
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS entries_object_id_idx ON entries(object_id)"
            )
            create_cleanup_clock(cursor, now_utc_ts())

    def get(self, key: str) -> tuple[str, IndexedMetadata] | None:
        """Return the object id and metadata for key."""
        with self._db.transition() as cursor:
            row = cursor.execute(
                """
                SELECT object_id, key, created_at, modified_at, last_access_time, size
                FROM entries WHERE key = ?
                """,
                (key,),
            ).fetchone()
        if row is None:
            return None
        object_id = row.pop("object_id")
        return object_id, IndexedMetadata(**row)

    def upsert(self, key: str, object_id: str, size: int, now: float) -> str | None:
        """Record a write of key and return the object id it replaced."""
        with self._db.transition() as cursor:
            previous = cursor.execute(
                "SELECT object_id FROM entries WHERE key = ?", (key,)
            ).fetchone()
            cursor.execute(
                """
                INSERT INTO entries
                    (key, object_id, created_at, modified_at, last_access_time, size)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    object_id = excluded.object_id,
                    modified_at = excluded.modified_at,
                    last_access_time = excluded.last_access_time,
                    size = excluded.size
                """,
                (key, object_id, now, now, now, size),
            )
        return None if previous is None else previous["object_id"]

    def touch(self, key: str, now: float) -> IndexedMetadata | None:
        """Record an access to key and return its updated metadata."""
        with self._db.transition() as cursor:
            row = cursor.execute(
                """
                UPDATE entries SET last_access_time = ? WHERE key = ?
                RETURNING key, created_at, modified_at, last_access_time, size
                """,
                (now, key),
            ).fetchone()
        return None if row is None else IndexedMetadata(**row)

    def delete(self, key: str) -> str | None:
        """Remove key and return the object id it referenced."""
        with self._db.transition() as cursor:
            row = cursor.execute(
                "DELETE FROM entries WHERE key = ? RETURNING object_id", (key,)
            ).fetchone()
        return None if row is None else row["object_id"]

    def keys(self) -> list[str]:
        with self._db.transition() as cursor:
            rows = cursor.execute("SELECT key FROM entries ORDER BY key").fetchall()
        return [row["key"] for row in rows]

    def object_ids(self) -> set[str]:
        with self._db.transition() as cursor:
            rows = cursor.execute("SELECT DISTINCT object_id FROM entries").fetchall()
        return {row["object_id"] for row in rows}

    def is_referenced(self, object_id: str) -> bool:
        with self._db.transition() as cursor:
            row = cursor.execute(
                "SELECT 1 FROM entries WHERE object_id = ? LIMIT 1", (object_id,)
            ).fetchone()
        return row is not None

    def claim_cleanup(self, interval: float, now: float) -> bool:
        with self._db.transition() as cursor:
            return claim_cleanup(cursor, interval, now)

    def close(self) -> None:
        self._db.close()
