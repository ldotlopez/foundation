from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from ..dblib import SQLite3DB


@dataclass(frozen=True)
class _IndexedEntryMetadata:
    key: str
    created_at: float
    modified_at: float
    last_access_time: float
    size: int


class _MetadataIndex:
    """SQLite index for file-backed storage content."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = SQLite3DB(db_path, use_dict_rows=True)
        with self._db.transition() as cursor:
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS entries ("
                "key TEXT PRIMARY KEY, "
                "object_id TEXT NOT NULL, "
                "created_at REAL NOT NULL, "
                "modified_at REAL NOT NULL, "
                "last_access_time REAL NOT NULL, "
                "size INTEGER NOT NULL"
                ")"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS entries_object_id_idx ON entries(object_id)"
            )

    def get(self, key: str) -> tuple[str, _IndexedEntryMetadata] | None:
        with self._db.transition() as cursor:
            row = cursor.execute(
                "SELECT object_id, key, created_at, modified_at, "
                "last_access_time, size FROM entries WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None

            object_id = row.pop("object_id")
            return object_id, _IndexedEntryMetadata(**row)

    def set(self, key: str, object_id: str, size: int, now: float) -> str | None:
        with self._db.transition() as cursor:
            previous = cursor.execute(
                "SELECT object_id FROM entries WHERE key = ?", (key,)
            ).fetchone()
            cursor.execute(
                "INSERT INTO entries "
                "(key, object_id, created_at, modified_at, last_access_time, size) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "object_id = excluded.object_id, "
                "modified_at = excluded.modified_at, "
                "last_access_time = excluded.last_access_time, "
                "size = excluded.size",
                (key, object_id, now, now, now, size),
            )
        return None if previous is None else previous["object_id"]

    def register(
        self,
        key: str,
        object_id: str,
        created_at: float,
        modified_at: float,
        last_access_time: float,
        size: int,
    ) -> None:
        with self._db.transition() as cursor:
            cursor.execute(
                "INSERT OR IGNORE INTO entries "
                "(key, object_id, created_at, modified_at, last_access_time, size) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    key,
                    object_id,
                    created_at,
                    modified_at,
                    last_access_time,
                    size,
                ),
            )

    def touch(self, key: str, now: float, size: int) -> _IndexedEntryMetadata | None:
        with self._db.transition() as cursor:
            row = cursor.execute(
                "UPDATE entries SET last_access_time = ?, size = ? "
                "WHERE key = ? RETURNING created_at, modified_at",
                (now, size, key),
            ).fetchone()
        if row is None:
            return None
        return _IndexedEntryMetadata(
            key=key,
            created_at=row["created_at"],
            modified_at=row["modified_at"],
            last_access_time=now,
            size=size,
        )

    def delete(self, key: str) -> str | None:
        with self._db.transition() as cursor:
            row = cursor.execute(
                "DELETE FROM entries WHERE key = ? RETURNING object_id", (key,)
            ).fetchone()
        return None if row is None else row["object_id"]

    def iter_keys(self) -> Iterator[str]:
        with self._db.transition() as cursor:
            keys = [
                row["key"]
                for row in cursor.execute("SELECT key FROM entries ORDER BY key")
            ]
        yield from keys

    def object_is_referenced(self, object_id: str) -> bool:
        with self._db.transition() as cursor:
            row = cursor.execute(
                "SELECT 1 FROM entries WHERE object_id = ? LIMIT 1", (object_id,)
            ).fetchone()
        return row is not None

    def key_for_object(self, object_id: str) -> str | None:
        with self._db.transition() as cursor:
            row = cursor.execute(
                "SELECT key FROM entries WHERE object_id = ? LIMIT 1", (object_id,)
            ).fetchone()
        return None if row is None else row["key"]

    def close(self) -> None:
        self._db.close()
