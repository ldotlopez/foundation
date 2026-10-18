from typing import Protocol

from ..dtlib import now_utc_ts
from ..storage import HasModifiedTime, StorageEntryMetadata


class Validator[T](Protocol):
    """Decides whether a single cache entry is still valid."""

    def is_valid(self, metadata: T) -> bool:
        """Return True if the entry described by metadata is still valid."""
        ...


class NullValidator(Validator[StorageEntryMetadata]):
    """Validator that accepts all entries."""

    def is_valid(self, metadata: StorageEntryMetadata) -> bool:
        return True


class TTLValidator(Validator[HasModifiedTime]):
    """Rejects entries modified more than expiration_time seconds ago."""

    def __init__(self, expiration_time: float) -> None:
        if expiration_time <= 0:
            raise ValueError(f"expiration_time must be positive: {expiration_time}")
        self.expiration_time = expiration_time

    def is_valid(self, metadata: HasModifiedTime) -> bool:
        if not isinstance(metadata, HasModifiedTime):
            raise TypeError("TTLValidator requires storage metadata with modified_at")
        return now_utc_ts() - metadata.modified_at <= self.expiration_time
