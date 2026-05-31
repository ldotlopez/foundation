from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class StorageEntryMetadata:
    """Base metadata for a storage entry."""

    key: str


class BaseStorage(ABC):
    """Abstract base class for storage backends."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Retrieve value for key. Raises MissingKeyError if not found."""
        ...

    @abstractmethod
    def set(self, key: str, value: bytes) -> None:
        """Store value for key."""
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete value for key. Should not raise if key doesn't exist."""
        ...

    @abstractmethod
    def get_metadata(self, key: str) -> StorageEntryMetadata:
        """Return storage metadata for key. Raises ItemNotFoundError if not found."""
        ...

    @abstractmethod
    def iter(self) -> Iterator[str]:
        """Iterate over all keys in storage."""
        ...


class ItemNotFoundError(Exception):
    def __init__(self, item: str):
        self.item = item


from .diskstorage import DiskStorage, DiskStorageEntryMetadata  # noqa: E402

__all__ = [
    "BaseStorage",
    "StorageEntryMetadata",
    "DiskStorage",
    "DiskStorageEntryMetadata",
]
