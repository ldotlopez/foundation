from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from ..storage import (
    BaseStorage,
    DiskStorage,
    EntryNotFoundError,
    StorageCorruptionError,
    StorageEntryMetadata,
)
from .eviction import EvictionPolicy
from .exc import ExpiredKeyError, MissingKeyError
from .validation import NullValidator, Validator


@dataclass(slots=True)
class PruneReport:
    """What prune() removed, or would remove during a dry run."""

    # Invalid entries, then entries evicted by the policy.
    removed: list[StorageEntryMetadata] = field(default_factory=list)
    # Keys of corrupt entries; they have no readable metadata.
    corrupt: list[str] = field(default_factory=list)
    # Paths the storage's cleanup() removed.
    cleaned: list[str] = field(default_factory=list)


class Cache:
    """Thin wrapper that combines storage, validation, and (optionally)
    cache-wide eviction.

    prune() is a manual operation: call it when the application decides,
    e.g. once per run in a CLI tool. Pruning is best-effort and is not
    synchronized with concurrent cache operations or other processes
    using the same storage.
    """

    def __init__(
        self,
        storage: BaseStorage | None = None,
        validator: Validator[Any] | None = None,
        eviction_policy: EvictionPolicy[Any] | None = None,
        eviction_check_interval: int = 100,
    ) -> None:
        """
        Args:
            storage: Backend to use. DiskStorage() if omitted.
            validator: Per-entry validity check. NullValidator()
                (accepts everything) if omitted.
            eviction_policy: Optional cache-wide capacity constraint
                (e.g. MaxEntriesEvictionPolicy, SizeEvictionPolicy).
                None means no capacity enforcement at all - the cache
                can grow without bound.
            eviction_check_interval: When eviction_policy is set,
                set() also calls prune() every this-many writes made
                through this instance. The count is in memory and
                starts at zero for each instance, so short-lived
                processes may never reach it and must call prune()
                themselves. Ignored if eviction_policy is None. Must
                be positive.
        """
        if eviction_check_interval <= 0:
            raise ValueError(
                f"eviction_check_interval must be positive: {eviction_check_interval}"
            )
        self.storage = storage if storage is not None else DiskStorage()
        self.validator: Validator[Any] = validator or NullValidator()
        self.eviction_policy: EvictionPolicy[Any] | None = eviction_policy
        self.eviction_check_interval = eviction_check_interval
        self._writes_since_eviction_check = 0

    def set(self, key: str, value: bytes) -> None:
        self.storage.set(key, value)

        if self.eviction_policy is not None:
            self._writes_since_eviction_check += 1
            if self._writes_since_eviction_check >= self.eviction_check_interval:
                self._writes_since_eviction_check = 0
                self.prune()

    def get(self, key: str) -> bytes:
        try:
            value, entry = self.storage.get_with_metadata(key)
        except EntryNotFoundError as e:
            raise MissingKeyError(key) from e
        except StorageCorruptionError as e:
            # A corrupt entry is unrecoverable; for a cache that is a miss.
            self.storage.delete(key)
            raise MissingKeyError(key) from e

        if not self.validator.is_valid(entry):
            self.storage.delete(key)
            raise ExpiredKeyError(key)

        return value

    def delete(self, key: str) -> None:
        self.storage.delete(key)

    def iter(self) -> Iterator[str]:
        return self.storage.iter()

    def prune(self, *, dry_run: bool = False) -> PruneReport:
        """Remove invalid and corrupt entries, then (if an eviction_policy
        is set) evict enough of the remaining valid entries to satisfy it.
        Finally run the backend's cleanup().

        A dry run reports the same entries without deleting them. Its
        cleanup report cannot include files that the entry deletions
        would free.
        """
        report = PruneReport()
        valid_entries: list[StorageEntryMetadata] = []

        for key in list(self.storage.iter()):
            try:
                entry = self.storage.get_metadata(key)
            except EntryNotFoundError:
                continue
            except StorageCorruptionError:
                report.corrupt.append(key)
                if not dry_run:
                    self.storage.delete(key)
                continue

            if not self.validator.is_valid(entry):
                report.removed.append(entry)

                if not dry_run:
                    self.storage.delete(key)
            else:
                valid_entries.append(entry)

        if self.eviction_policy is not None:
            to_evict = self.eviction_policy.select_for_eviction(valid_entries)

            for entry in to_evict:
                if not dry_run:
                    self.storage.delete(entry.key)

            report.removed.extend(to_evict)

        report.cleaned = self.storage.cleanup(dry_run=dry_run)
        return report

    def close(self) -> None:
        """Close the underlying storage."""
        self.storage.close()
