from __future__ import annotations

import errno
import hashlib
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

from ..dtlib import now_utc_ts
from . import (
    BaseStorage,
    EntryNotFoundError,
    StorageCorruptionError,
    StorageEntryMetadata,
)
from ._index import _MetadataIndex


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary.write(value)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


class _HashedFileStorage(BaseStorage):
    def __init__(self, base_dir: Path | None, index_name: str, object_dir: str) -> None:
        if base_dir is None:
            base_dir = Path(tempfile.mkdtemp())
        self.base_dir = base_dir
        self.object_dir = base_dir / object_dir
        self.object_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_path = base_dir / index_name
        self._index = _MetadataIndex(self.metadata_path)

    def _object_path(self, object_id: str) -> Path:
        return self.object_dir / object_id[:2] / object_id

    def _read_indexed(self, key: str) -> tuple[str, StorageEntryMetadata]:
        indexed = self._index.get(key)
        if indexed is None:
            raise EntryNotFoundError(key)
        return indexed

    def get_metadata(self, key: str) -> StorageEntryMetadata:
        _, metadata = self._read_indexed(key)
        return metadata

    def get_with_metadata(self, key: str) -> tuple[bytes, StorageEntryMetadata]:
        object_id, _ = self._read_indexed(key)
        value = self._read_object(key, object_id)
        metadata = self._index.touch(key, now_utc_ts(), len(value))
        if metadata is None:
            raise EntryNotFoundError(key)
        return value, metadata

    def get(self, key: str) -> bytes:
        object_id, _ = self._read_indexed(key)
        return self._read_object(key, object_id)

    def iter(self) -> Iterator[str]:
        yield from self._index.iter_keys()

    def _read_object(self, key: str, object_id: str) -> bytes:
        path = self._object_path(object_id)
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            raise StorageCorruptionError(
                key, f"backing object {object_id!r} is missing"
            ) from error

    def _remove_object(self, object_id: str) -> None:
        path = self._object_path(object_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return
        try:
            path.parent.rmdir()
        except OSError as error:
            if error.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                raise

    def cleanup(self, *, dry_run: bool = False) -> list[str]:
        removed: list[str] = []
        shard_dirs = sorted(
            (path for path in self.object_dir.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for shard_dir in shard_dirs:
            try:
                next(shard_dir.iterdir())
            except StopIteration:
                removed.append(str(shard_dir))
                if not dry_run:
                    shard_dir.rmdir()
            except FileNotFoundError:
                continue
        return removed

    def close(self) -> None:
        """Close the SQLite metadata index connection."""
        self._index.close()


class KeyHashStorage(_HashedFileStorage):
    """File-backed key-value storage addressed by SHA-256 hashes of keys.

    The SQLite sidecar stores original keys and metadata; values remain
    separate files under ``base_dir``. Keys can contain arbitrary characters.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        super().__init__(base_dir, "key-hash-metadata.sqlite3", "key-objects")

    def set(self, key: str, value: bytes) -> None:
        object_id = _sha256(key.encode("utf-8"))
        existing_key = self._index.key_for_object(object_id)
        if existing_key is not None and existing_key != key:
            raise StorageCorruptionError(
                key, f"SHA-256 key digest collides with key {existing_key!r}"
            )
        _atomic_write(self._object_path(object_id), value)
        self._index.set(key, object_id, len(value), now_utc_ts())

    def delete(self, key: str) -> None:
        object_id = self._index.delete(key)
        if object_id is not None:
            self._remove_object(object_id)


class ValueHashStorage(_HashedFileStorage):
    """File-backed key-value storage with SHA-256-addressed, deduplicated blobs."""

    def __init__(self, base_dir: Path | None = None) -> None:
        super().__init__(base_dir, "value-hash-metadata.sqlite3", "value-objects")

    def set(self, key: str, value: bytes) -> None:
        object_id = _sha256(value)
        object_path = self._object_path(object_id)
        if object_path.exists():
            existing_value = object_path.read_bytes()
            if existing_value != value or _sha256(existing_value) != object_id:
                raise StorageCorruptionError(
                    key,
                    f"backing object {object_id!r} has different content "
                    "or failed digest verification",
                )
        else:
            _atomic_write(object_path, value)

        previous_object_id = self._index.set(key, object_id, len(value), now_utc_ts())
        if (
            previous_object_id is not None
            and previous_object_id != object_id
            and not self._index.object_is_referenced(previous_object_id)
        ):
            self._remove_object(previous_object_id)

    def _read_object(self, key: str, object_id: str) -> bytes:
        value = super()._read_object(key, object_id)
        if _sha256(value) != object_id:
            raise StorageCorruptionError(
                key, f"backing object {object_id!r} failed digest verification"
            )
        return value

    def delete(self, key: str) -> None:
        object_id = self._index.delete(key)
        if object_id is not None and not self._index.object_is_referenced(object_id):
            self._remove_object(object_id)
