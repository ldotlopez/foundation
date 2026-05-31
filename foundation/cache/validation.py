from __future__ import annotations

from abc import abstractmethod
from datetime import datetime

from ..storage import StorageEntryMetadata


class Validator:
    """Abstract base class for cache validators."""

    @abstractmethod
    def is_valid(self, metadata: StorageEntryMetadata) -> bool:
        """Check if a cache entry's metadata is valid."""
        ...


class NullValidator(Validator):
    """Validator that accepts all entries."""

    def is_valid(self, metadata: StorageEntryMetadata) -> bool:
        return True


class StorageValidator(Validator):
    """Legacy alias for validators that operate on StorageEntryMetadata."""


class StatValidator(StorageValidator):
    """Validator based on modification time metadata."""

    def __init__(self, expiration_time: float):
        self.expiration_time: float = expiration_time

    def _now_ts(self) -> float:
        return datetime.now().timestamp()

    def is_valid(self, metadata: StorageEntryMetadata) -> bool:
        """Check if a cache entry hasn't expired based on modification time.

        Returns:
            True if the entry is still valid (not expired), False otherwise
        """
        delta = self._now_ts() - metadata.modified_at
        return delta <= self.expiration_time


# Keep old names for backwards compatibility
ValidationPolicy = Validator
NullValidationPolicy = NullValidator
