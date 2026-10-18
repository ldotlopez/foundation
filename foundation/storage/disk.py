import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from os import stat_result
from pathlib import Path

from ..dtlib import now_utc_ts
from ._base import EntryNotFoundError, validate_path_component
from ._files import (
    atomic_write,
    read_backing_file,
    remove_dir_if_empty,
    remove_empty_shard_dirs,
    stat_backing_file,
)
from ._index import IndexedMetadata, MetadataIndex


@dataclass(frozen=True, slots=True)
class DiskStorageEntryMetadata:
    """Disk-specific metadata for a storage entry."""

    key: str
    created_at: float
    modified_at: float
    last_access_time: float
    size: int
    path: Path
    stat: stat_result


class DiskStorage:
    """One file per key under ``base_dir/<key[:2]>/<key>``.

    Keys must be safe single path components. A SQLite index beside the
    files is the source of truth: files without an index row are ignored.
    """

    def __init__(
        self,
        base_dir: Path | None = None,
        dir_mode: int | None = None,
        cleanup_interval: float | None = None,
    ) -> None:
        """Create disk-backed storage.

        Args:
            base_dir: Root directory for entries. If omitted, a temporary
                directory is used and removed by close().
            dir_mode: Exact permission bits (e.g. 0o700) for base_dir and
                every shard directory created under it.
            cleanup_interval: If given, run cleanup() on open when at least
                this many seconds passed since the last run.
        """
        # A store in a temporary directory owns it and removes it on close().
        self._temporary_dir: tempfile.TemporaryDirectory[str] | None = None
        if base_dir is None:
            self._temporary_dir = tempfile.TemporaryDirectory()
            base_dir = Path(self._temporary_dir.name)
        self.base_dir = base_dir
        self.dir_mode = dir_mode
        self._mkdir(self.base_dir)
        self._index = MetadataIndex(self.base_dir / "disk-metadata.sqlite3")
        if cleanup_interval is not None and self._index.claim_cleanup(
            cleanup_interval, now_utc_ts()
        ):
            self.cleanup()

    def get(self, key: str) -> bytes:
        value, _ = self.get_with_metadata(key)
        return value

    def set(self, key: str, value: bytes) -> None:
        path = self._path(key)
        self._mkdir(path.parent)
        try:
            atomic_write(path, value)
        except FileNotFoundError:
            # A concurrent delete() removed the emptied shard dir; recreate it.
            self._mkdir(path.parent)
            atomic_write(path, value)
        self._index.upsert(key, key, len(value), now_utc_ts())

    def delete(self, key: str) -> None:
        path = self._path(key)
        if self._index.delete(key) is not None:
            path.unlink(missing_ok=True)
            remove_dir_if_empty(path.parent)

    def get_metadata(self, key: str) -> DiskStorageEntryMetadata:
        path, metadata = self._locate(key)
        return self._disk_metadata(metadata, path, stat_backing_file(key, path))

    def get_with_metadata(self, key: str) -> tuple[bytes, DiskStorageEntryMetadata]:
        path, _ = self._locate(key)
        value = read_backing_file(key, path)
        stat = stat_backing_file(key, path)
        metadata = self._index.touch(key, now_utc_ts())
        if metadata is None:
            raise EntryNotFoundError(key)
        return value, self._disk_metadata(metadata, path, stat)

    def iter(self) -> Iterator[str]:
        yield from self._index.keys()

    def cleanup(self, *, dry_run: bool = False) -> list[str]:
        """Remove empty shard directories that delete() left behind."""
        return remove_empty_shard_dirs(self.base_dir, dry_run=dry_run)

    def close(self) -> None:
        """Close the index and remove the directory if it is temporary."""
        self._index.close()
        if self._temporary_dir is not None:
            self._temporary_dir.cleanup()

    def _path(self, key: str) -> Path:
        validate_path_component(key)
        return self.base_dir / key[:2] / key

    def _locate(self, key: str) -> tuple[Path, IndexedMetadata]:
        path = self._path(key)
        indexed = self._index.get(key)
        if indexed is None:
            raise EntryNotFoundError(key)
        _, metadata = indexed
        return path, metadata

    def _mkdir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if self.dir_mode is not None:
            # mkdir's mode is masked by the umask; chmod sets the exact bits.
            path.chmod(self.dir_mode)

    @staticmethod
    def _disk_metadata(
        metadata: IndexedMetadata, path: Path, stat: stat_result
    ) -> DiskStorageEntryMetadata:
        return DiskStorageEntryMetadata(
            key=metadata.key,
            created_at=metadata.created_at,
            modified_at=metadata.modified_at,
            last_access_time=metadata.last_access_time,
            size=metadata.size,
            path=path,
            stat=stat,
        )
