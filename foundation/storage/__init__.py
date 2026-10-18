from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageEntryMetadata(Protocol):
    """Minimal metadata contract shared by all storage backends."""

    @property
    def key(self) -> str: ...


@runtime_checkable
class HasCreatedTime(Protocol):
    """Metadata capability for creation timestamps."""

    @property
    def created_at(self) -> float: ...


@runtime_checkable
class HasModifiedTime(Protocol):
    """Metadata capability for modification timestamps."""

    @property
    def modified_at(self) -> float: ...


@runtime_checkable
class HasLastAccessTime(Protocol):
    """Metadata capability for last-access timestamps."""

    @property
    def last_access_time(self) -> float: ...


@runtime_checkable
class HasSize(Protocol):
    """Metadata capability for logical value size in bytes."""

    @property
    def size(self) -> int: ...


@runtime_checkable
class HasLastAccessTimeAndSize(HasLastAccessTime, HasSize, Protocol):
    """Metadata capability required by size-based LRU eviction."""


class BaseStorage(ABC):
    """Abstract base class for storage backends."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Retrieve value for key. Raises EntryNotFoundError if not found."""
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
        """Return storage metadata for key. Raises EntryNotFoundError if not found."""
        ...

    @abstractmethod
    def iter(self) -> Iterator[str]:
        """Iterate over all keys in storage."""
        ...

    def get_with_metadata(self, key: str) -> tuple[bytes, StorageEntryMetadata]:
        """Retrieve a value and its metadata.

        Backends that provide access-time metadata should update it as part
        of this operation. The default implementation makes two calls and
        does not provide atomicity.
        """
        value = self.get(key)
        metadata = self.get_metadata(key)
        return value, metadata

    def cleanup(self, *, dry_run: bool = False) -> list[str]:
        """Perform backend-specific maintenance unrelated to entry validity.

        This is distinct from a cache-level prune: it does not remove
        entries based on whether they're still valid. It cleans up
        internal storage artifacts left behind by normal operation
        (e.g. empty directories after deletes), regardless of why or
        how those deletes happened.

        Backends that don't need maintenance can leave this as a no-op.

        Returns:
            A list of description strings for what was (or, if
            dry_run, would be) cleaned up. Empty if nothing to do.
        """
        return []


class EntryNotFoundError(Exception):
    def __init__(self, entry: str):
        self.entry = entry


class StorageCorruptionError(Exception):
    """An indexed storage entry has missing or invalid backing content."""

    def __init__(self, entry: str, detail: str) -> None:
        self.entry = entry
        self.detail = detail
        super().__init__(f"Storage entry {entry!r} is corrupt: {detail}")


def validate_path_component(value: str) -> None:
    """Reject a string that isn't safe to use as a single filesystem
    path segment (a key, an app name, etc.).

    Centralized here so every place that turns a caller-supplied
    string into part of a filesystem path — DiskStorage keys today,
    UserCache's app name, anything similar later — shares one check
    instead of each call site reimplementing (and potentially
    forgetting) traversal safety.
    """
    if not value or "/" in value or "\\" in value or value in (".", ".."):
        raise ValueError(f"Invalid path component: {value!r}")


from .disk import DiskStorage, DiskStorageEntryMetadata
from .hashed import KeyHashStorage, ValueHashStorage
from .sqlite import SqliteStorage, SqliteStorageEntryMetadata

__all__ = [
    "BaseStorage",
    "DiskStorage",
    "DiskStorageEntryMetadata",
    "HasCreatedTime",
    "HasLastAccessTime",
    "HasLastAccessTimeAndSize",
    "HasModifiedTime",
    "HasSize",
    "KeyHashStorage",
    "SqliteStorage",
    "SqliteStorageEntryMetadata",
    "StorageCorruptionError",
    "StorageEntryMetadata",
    "ValueHashStorage",
    "validate_path_component",
]
