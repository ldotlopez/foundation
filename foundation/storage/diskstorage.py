from __future__ import annotations

import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from . import BaseStorage, ItemNotFoundError, StorageEntryMetadata


@dataclass(frozen=True)
class DiskStorageEntryMetadata(StorageEntryMetadata):
    """Disk-specific metadata for a storage entry."""

    modified_at: float
    path: Path | None = None


class DiskStorage(BaseStorage):
    """File-based storage using disk directories."""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path(tempfile.mkdtemp())
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def set(self, key: str, value: bytes) -> None:
        filepath = self._build_path(key)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_bytes(value)

    def get(self, key: str) -> bytes:
        filepath = self._build_path(key)
        try:
            return filepath.read_bytes()
        except FileNotFoundError as e:
            raise ItemNotFoundError(key) from e

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
            raise ItemNotFoundError(key) from e
        return DiskStorageEntryMetadata(
            key=key, modified_at=stat.st_mtime, path=filepath
        )

    def iter(self) -> Iterator[str]:
        # Check the glob expresion against _build_path structure
        yield from (x.name for x in self.base_dir.rglob("*/*") if x.is_file())

    @lru_cache
    def _build_path(self, key: str) -> Path:
        return Path(self.base_dir / key[0:2] / key)
