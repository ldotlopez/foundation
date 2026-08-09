from __future__ import annotations

from abc import abstractmethod
from typing import Protocol, runtime_checkable

from ..dtlib import now_utc_ts
from ..storage import StorageEntryMetadata


class Validator[T]:
    """Abstract base class for cache validators."""

    @abstractmethod
    def is_valid(self, metadata: T) -> bool:
        """Check if a cache entry's metadata is valid."""
        ...


class NullValidator(Validator[StorageEntryMetadata]):
    """Validator that accepts all entries."""

    def is_valid(self, metadata: StorageEntryMetadata) -> bool:
        return True


@runtime_checkable
class HasModifiedTime(Protocol):
    """Structural contract for metadata carrying a modification time.

    TTLValidator only needs a timestamp, not any particular storage
    backend's representation of one. Any StorageEntryMetadata subclass
    (disk, sqlite, etc.) satisfies this by exposing modified_at,
    without cache/validation.py needing to import or know about that
    backend.
    """

    @property
    def modified_at(self) -> float: ...


class TTLValidator(Validator[HasModifiedTime]):
    """Validator based on modification time metadata."""

    def __init__(self, expiration_time: float):
        self.expiration_time: float = expiration_time

    def is_valid(self, metadata: HasModifiedTime) -> bool:
        """Check if a cache entry hasn't expired based on modification time.

        Returns:
            True if the entry is still valid (not expired), False otherwise
        """
        delta = now_utc_ts() - metadata.modified_at
        return delta <= self.expiration_time
