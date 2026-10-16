from __future__ import annotations

from abc import abstractmethod

from ..dtlib import now_utc_ts
from ..storage import StorageEntryMetadata
from .protocols import HasModifiedTime


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


class TTLValidator(Validator[HasModifiedTime]):
    """Validator based on modification time metadata."""

    def __init__(self, expiration_time: float):
        self.expiration_time: float = expiration_time

    def is_valid(self, metadata: HasModifiedTime) -> bool:
        """Check if a cache entry hasn't expired based on modification time.

        Returns:
            True if the entry is still valid (not expired), False otherwise
        """
        if not isinstance(metadata, HasModifiedTime):
            raise TypeError("TTLValidator requires metadata with modified_at")

        delta = now_utc_ts() - metadata.modified_at
        return delta <= self.expiration_time
