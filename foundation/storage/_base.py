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


class BaseStorage(Protocol):
    """Byte key-value storage contract implemented by every backend."""

    def get(self, key: str) -> bytes:
        """Return the value for key, recording the access time.

        Equivalent to get_with_metadata() without the metadata. Raise
        EntryNotFoundError if absent.
        """
        ...

    def set(self, key: str, value: bytes) -> None:
        """Store value under key, replacing any previous value."""
        ...

    def delete(self, key: str) -> None:
        """Remove key. Do nothing if it is absent."""
        ...

    def get_metadata(self, key: str) -> StorageEntryMetadata:
        """Return metadata for key without recording an access.

        Raise EntryNotFoundError if absent. An entry whose backing content
        is found missing is deleted and reported as absent.
        """
        ...

    def get_with_metadata(self, key: str) -> tuple[bytes, StorageEntryMetadata]:
        """Return value and metadata for key, recording the access time.

        Raise EntryNotFoundError if absent. Backing content that is
        missing or corrupt cannot be recovered, so its entry is deleted
        and reported as absent.
        """
        ...

    def iter(self) -> Iterator[str]:
        """Iterate over all stored keys."""
        ...

    def cleanup(self, *, dry_run: bool = False) -> list[str]:
        """Remove internal artifacts left behind by normal operation.

        This is backend maintenance, not cache pruning: it never removes
        live entries. Return a description of each artifact removed (or,
        with dry_run, that would be removed).
        """
        ...

    def claim_maintenance(self, interval: float) -> bool:
        """Claim a maintenance run if the last one is interval seconds old.

        The last run time is persisted with the store and claimed
        atomically, so of several processes only one gets each run. A new
        store counts as just maintained. The caller performs the run.
        """
        ...

    def close(self) -> None:
        """Release the resources held by the backend."""
        ...


class EntryNotFoundError(Exception):
    """The requested key is not stored."""

    def __init__(self, entry: str) -> None:
        self.entry = entry
        super().__init__(entry)


def validate_path_component(value: str) -> None:
    """Raise ValueError unless value is safe as a single path segment."""
    if not value or "/" in value or "\\" in value or value in (".", ".."):
        raise ValueError(f"Invalid path component: {value!r}")
