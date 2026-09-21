from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from os import stat_result
from pathlib import Path

import filelock

from ..dtlib import now_utc_ts
from . import (
    BaseStorage,
    EntryNotFoundError,
    StorageEntryMetadata,
    validate_path_component,
)


@dataclass(frozen=True)
class DiskStorageEntryMetadata(StorageEntryMetadata):
    """Disk-specific metadata for a storage entry."""

    path: Path
    stat: stat_result

    @property
    def modified_at(self) -> float:
        """Modification time as a portable float timestamp.

        Satisfies cache.protocols.HasModifiedTime without callers
        needing to know this backend represents it via stat_result.
        """
        return self.stat.st_mtime

    @property
    def size(self) -> int:
        """Entry size in bytes. Satisfies cache.protocols.HasSize."""
        return self.stat.st_size

    @property
    def last_access_time(self) -> float:
        """Last-access time as a portable float timestamp.

        Satisfies cache.protocols.HasLastAccessTime. Reflects whatever
        the OS currently reports for atime - this is only kept
        accurate for eviction purposes once reads go through
        get_and_touch(), which explicitly rewrites atime via
        os.utime() rather than relying on the OS to update it
        (mount options like noatime/relatime often mean it won't).
        """
        return self.stat.st_atime


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

    def _mkdir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if self.dir_mode is not None:
            # mkdir's own `mode` argument is masked by the process
            # umask, so chmod explicitly to get the exact bits requested.
            path.chmod(self.dir_mode)

    def set(self, key: str, value: bytes) -> None:
        filepath = self._build_path(key)
        self._mkdir(filepath.parent)
        filepath.write_bytes(value)

    def get(self, key: str) -> bytes:
        filepath = self._build_path(key)
        try:
            return filepath.read_bytes()
        except FileNotFoundError as e:
            raise EntryNotFoundError(key) from e

    def delete(self, key: str) -> None:
        filepath = self._build_path(key)
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

        return DiskStorageEntryMetadata(key=key, path=filepath, stat=stat)

    def get_and_touch(self, key: str) -> tuple[bytes, DiskStorageEntryMetadata]:
        """Read a value and record this as an access by explicitly
        rewriting atime (via os.utime, not relying on the OS - mount
        options like noatime/relatime commonly mean it wouldn't
        update atime on its own). mtime is preserved.

        Not perfectly atomic (read, then a separate utime, then a
        final stat are three syscalls, not one), but tighter than
        three independent high-level calls, and consistent with this
        backend's existing no-stronger-guarantee posture elsewhere.
        """
        filepath = self._build_path(key)
        try:
            value = filepath.read_bytes()
            stat_before = filepath.stat()
        except FileNotFoundError as e:
            raise EntryNotFoundError(key) from e

        os.utime(filepath, (now_utc_ts(), stat_before.st_mtime))
        stat_after = filepath.stat()
        return value, DiskStorageEntryMetadata(key=key, path=filepath, stat=stat_after)

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

        return removed

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        """Cross-process mutual exclusion via a lock file in base_dir.

        filelock (not stdlib fcntl) so this works on Windows too,
        not just POSIX - same reasoning as using platformdirs rather
        than hand-rolling per-OS cache-dir resolution. Wrapped rather
        than returning the FileLock object directly, so lock()'s
        contract (a context manager yielding None) stays uniform
        with SqliteStorage.lock() and BaseStorage's default.
        """
        with filelock.FileLock(str(self.base_dir / ".lock")):
            yield

    def _build_path(self, key: str) -> Path:
        validate_path_component(key)
        return Path(self.base_dir / key[0:2] / key)
