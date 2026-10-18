from __future__ import annotations

import errno
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from os import stat_result
from pathlib import Path

from ..dtlib import now_utc_ts
from . import (
    BaseStorage,
    EntryNotFoundError,
    validate_path_component,
)
from ._index import _MetadataIndex


@dataclass(frozen=True)
class DiskStorageEntryMetadata:
    """Disk-specific metadata for a storage entry."""

    key: str
    created_at: float
    modified_at: float
    last_access_time: float
    size: int
    path: Path
    stat: stat_result


class DiskStorage(BaseStorage):
    """File-based storage using disk directories."""

    def __init__(self, base_dir: Path | None = None, dir_mode: int | None = None):
        """Create disk-backed storage.

        Args:
            base_dir: Root directory for entries. A temp dir if omitted.
            dir_mode: If given, permission bits (e.g. 0o700) applied to
                base_dir and every shard directory created under it.
                DiskStorage has no opinion on what this should be —
                it's the caller's decision (see cache.UserCache for a
                caller that requests owner-only permissions).
        """
        self.base_dir = base_dir or Path(tempfile.mkdtemp())
        self.dir_mode = dir_mode
        self._mkdir(self.base_dir)
        self._index = _MetadataIndex(self.base_dir / "disk-metadata.sqlite3")

    def _mkdir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if self.dir_mode is not None:
            # mkdir's own `mode` argument is masked by the process
            # umask, so chmod explicitly to get the exact bits requested.
            path.chmod(self.dir_mode)

    def set(self, key: str, value: bytes) -> None:
        filepath = self._build_path(key)
        self._mkdir(filepath.parent)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=filepath.parent, delete=False
            ) as temporary:
                temporary.write(value)
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, filepath)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        self._index.set(key, key, len(value), now_utc_ts())

    def get(self, key: str) -> bytes:
        filepath = self._build_path(key)
        try:
            return filepath.read_bytes()
        except FileNotFoundError as e:
            raise EntryNotFoundError(key) from e

    def delete(self, key: str) -> None:
        filepath = self._build_path(key)
        self._index.delete(key)
        try:
            filepath.unlink()
        except FileNotFoundError:
            pass

    def get_metadata(self, key: str) -> DiskStorageEntryMetadata:
        filepath = self._build_path(key)

        try:
            stat = filepath.stat()
        except FileNotFoundError as e:
            raise EntryNotFoundError(key) from e

        indexed = self._index.get(key)
        if indexed is None:
            created_at = getattr(stat, "st_birthtime", stat.st_ctime)
            self._index.register(
                key,
                key,
                created_at,
                stat.st_mtime,
                stat.st_atime,
                stat.st_size,
            )
            indexed = self._index.get(key)
        if indexed is None:
            raise RuntimeError(f"Metadata index failed to register {key!r}")
        _, metadata = indexed
        return DiskStorageEntryMetadata(
            key=metadata.key,
            created_at=metadata.created_at,
            modified_at=metadata.modified_at,
            last_access_time=metadata.last_access_time,
            size=stat.st_size,
            path=filepath,
            stat=stat,
        )

    def get_with_metadata(self, key: str) -> tuple[bytes, DiskStorageEntryMetadata]:
        """Read a value and explicitly record the access time.

        This does not rely on filesystem mount options to update atime.
        """
        filepath = self._build_path(key)
        try:
            value = filepath.read_bytes()
            stat_before = filepath.stat()
            accessed_at = now_utc_ts()
            os.utime(filepath, (accessed_at, stat_before.st_mtime))
            stat_after = filepath.stat()
        except FileNotFoundError as e:
            raise EntryNotFoundError(key) from e
        indexed = self._index.get(key)
        if indexed is None:
            created_at = getattr(stat_after, "st_birthtime", stat_after.st_ctime)
            self._index.register(
                key,
                key,
                created_at,
                stat_after.st_mtime,
                stat_after.st_atime,
                stat_after.st_size,
            )
        metadata = self._index.touch(key, accessed_at, len(value))
        if metadata is None:
            raise RuntimeError(f"Metadata index failed to update {key!r}")
        return value, DiskStorageEntryMetadata(
            key=metadata.key,
            created_at=metadata.created_at,
            modified_at=metadata.modified_at,
            last_access_time=metadata.last_access_time,
            size=metadata.size,
            path=filepath,
            stat=stat_after,
        )

    def iter(self) -> Iterator[str]:
        # Check the glob expresion against _build_path structure
        yield from (x.name for x in self.base_dir.rglob("*/*") if x.is_file())

    def cleanup(self, *, dry_run: bool = False) -> list[str]:
        """Remove empty shard directories left behind by delete().

        delete() unlinks a file but never checks whether its parent
        shard directory (key[0:2]/) is now empty, so empty shard dirs
        can accumulate over time regardless of what triggered the
        deletes. This sweeps and removes them.
        """
        removed: list[str] = []

        for shard_dir in self.base_dir.iterdir():
            if not shard_dir.is_dir():
                continue
            try:
                next(shard_dir.iterdir())
            except StopIteration:
                removed.append(str(shard_dir))
                if not dry_run:
                    shard_dir.rmdir()
            except OSError as error:
                if error.errno != errno.ENOENT:
                    raise

        return removed

    def close(self) -> None:
        """Close the SQLite metadata index connection."""
        self._index.close()

    def _build_path(self, key: str) -> Path:
        validate_path_component(key)
        return Path(self.base_dir / key[0:2] / key)
