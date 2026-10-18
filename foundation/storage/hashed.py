import hashlib
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

from ..dtlib import now_utc_ts
from ._base import EntryNotFoundError, StorageEntryMetadata
from ._files import (
    atomic_write,
    remove_dir_if_empty,
    remove_empty_shard_dirs,
)
from ._index import IndexedMetadata, MetadataIndex

# Unindexed objects younger than this may belong to an in-flight set().
_ORPHAN_GRACE_SECONDS = 300.0


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class _HashedFileStorage:
    """File storage addressed by SHA-256 object ids, indexed in SQLite.

    Objects live at ``<object_dir>/<id[:2]>/<id>``. Subclasses decide what
    is hashed by overriding _object_id().
    """

    def __init__(
        self,
        base_dir: Path | None,
        index_name: str,
        object_dir: str,
    ) -> None:
        # A store in a temporary directory owns it and removes it on close().
        self._temporary_dir: tempfile.TemporaryDirectory[str] | None = None
        if base_dir is None:
            self._temporary_dir = tempfile.TemporaryDirectory()
            base_dir = Path(self._temporary_dir.name)
        self.base_dir = base_dir
        self.object_dir = self.base_dir / object_dir
        self.object_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_path = self.base_dir / index_name
        self._index = MetadataIndex(self.metadata_path)

    def get(self, key: str) -> bytes:
        value, _ = self.get_with_metadata(key)
        return value

    def set(self, key: str, value: bytes) -> None:
        object_id = self._object_id(key, value)
        path = self._object_path(object_id)
        path.parent.mkdir(exist_ok=True)
        try:
            self._write_object(key, path, value)
        except FileNotFoundError:
            # A concurrent delete() removed the emptied shard dir; recreate it.
            path.parent.mkdir(exist_ok=True)
            self._write_object(key, path, value)
        previous_id = self._index.upsert(key, object_id, len(value), now_utc_ts())
        if previous_id is not None and previous_id != object_id:
            self._release(previous_id)

    def delete(self, key: str) -> None:
        object_id = self._index.delete(key)
        if object_id is not None:
            self._release(object_id)

    def get_metadata(self, key: str) -> StorageEntryMetadata:
        _, metadata = self._locate(key)
        return metadata

    def get_with_metadata(self, key: str) -> tuple[bytes, StorageEntryMetadata]:
        object_id, _ = self._locate(key)
        value = self._read_object(object_id)
        if value is None:
            # Missing or corrupt content cannot be recovered: drop the entry.
            # A shared object goes once the last key referencing it is dropped.
            self.delete(key)
            raise EntryNotFoundError(key)
        metadata = self._index.touch(key, now_utc_ts())
        if metadata is None:
            raise EntryNotFoundError(key)
        return value, metadata

    def iter(self) -> Iterator[str]:
        yield from self._index.keys()

    def cleanup(self, *, dry_run: bool = False) -> list[str]:
        """Remove unreferenced objects, then empty shard directories.

        Unreferenced objects are left by a crash between writing an object
        and indexing it. Objects modified within the last
        _ORPHAN_GRACE_SECONDS are kept, so cleanup is safe alongside set()
        in other processes.
        """
        referenced = self._index.object_ids()
        cutoff = now_utc_ts() - _ORPHAN_GRACE_SECONDS
        removed: list[str] = []
        for path in sorted(self.object_dir.glob("*/*")):
            if (
                path.is_file()
                and path.name not in referenced
                and path.stat().st_mtime < cutoff
            ):
                removed.append(str(path))
                if not dry_run:
                    path.unlink(missing_ok=True)
        removed.extend(
            remove_empty_shard_dirs(
                self.object_dir, dry_run=dry_run, removed_paths=set(removed)
            )
        )
        return removed

    def claim_maintenance(self, interval: float) -> bool:
        return self._index.claim_maintenance(interval, now_utc_ts())

    def close(self) -> None:
        """Close the index and remove the directory if it is temporary."""
        self._index.close()
        if self._temporary_dir is not None:
            self._temporary_dir.cleanup()

    def _object_id(self, key: str, value: bytes) -> str:
        raise NotImplementedError

    def _object_path(self, object_id: str) -> Path:
        return self.object_dir / object_id[:2] / object_id

    def _locate(self, key: str) -> tuple[str, IndexedMetadata]:
        indexed = self._index.get(key)
        if indexed is None:
            raise EntryNotFoundError(key)
        return indexed

    def _read_object(self, object_id: str) -> bytes | None:
        """Return the object's content, or None if it is missing or corrupt."""
        try:
            return self._object_path(object_id).read_bytes()
        except FileNotFoundError:
            return None

    def _write_object(self, key: str, path: Path, value: bytes) -> None:
        atomic_write(path, value)

    def _release(self, object_id: str) -> None:
        if not self._index.is_referenced(object_id):
            path = self._object_path(object_id)
            path.unlink(missing_ok=True)
            remove_dir_if_empty(path.parent)


class KeyHashStorage(_HashedFileStorage):
    """File storage addressed by the SHA-256 of each key.

    Keys may contain any characters; the index keeps the original key.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        super().__init__(base_dir, "key-hash-metadata.sqlite3", "key-objects")

    def _object_id(self, key: str, value: bytes) -> str:
        return _sha256(key.encode("utf-8"))


class ValueHashStorage(_HashedFileStorage):
    """File storage addressed by the SHA-256 of each value.

    Equal values share one object; reads verify the object's digest.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        super().__init__(base_dir, "value-hash-metadata.sqlite3", "value-objects")

    def _object_id(self, key: str, value: bytes) -> str:
        return _sha256(value)

    def _read_object(self, object_id: str) -> bytes | None:
        value = super()._read_object(object_id)
        if value is None or _sha256(value) != object_id:
            return None
        return value

    def _write_object(self, key: str, path: Path, value: bytes) -> None:
        try:
            if path.read_bytes() == value:
                # Restart the cleanup grace period; raises if cleanup removed it.
                os.utime(path)
                return
        except FileNotFoundError:
            pass
        # Missing or corrupt: content addressing makes rewriting it safe.
        atomic_write(path, value)
