from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Self

from ..storage import (
    BaseStorage,
    DiskStorage,
    EntryNotFoundError,
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
    # Paths the storage's cleanup() removed.
    cleaned: list[str] = field(default_factory=list)


class Cache:
    """Thin wrapper that combines storage, validation, and (optionally)
    cache-wide eviction.

    prune() runs when called, or on open once prune_interval has passed.
    Pruning is best-effort and is not synchronized with concurrent cache
    operations or other processes using the same storage.

    Usable as a context manager that closes the cache on exit.
    """

    def __init__(
        self,
        storage: BaseStorage | None = None,
        validator: Validator[Any] | None = None,
        eviction_policy: EvictionPolicy[Any] | None = None,
        prune_interval: float | None = None,
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
            prune_interval: If given, prune() on open when at least
                this many seconds passed since the storage was last
                maintained, by any process (see
                BaseStorage.claim_maintenance). Must be positive.
        """
        if prune_interval is not None and prune_interval <= 0:
            raise ValueError(f"prune_interval must be positive: {prune_interval}")
        self.storage = storage if storage is not None else DiskStorage()
        self.validator: Validator[Any] = validator or NullValidator()
        self.eviction_policy: EvictionPolicy[Any] | None = eviction_policy
        if prune_interval is not None and self.storage.claim_maintenance(
            prune_interval
        ):
            self.prune()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def set(self, key: str, value: bytes) -> None:
        self.storage.set(key, value)

    def get(self, key: str) -> bytes:
        try:
            value, entry = self.storage.get_with_metadata(key)
        except EntryNotFoundError as e:
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
        """Remove invalid entries, then (if an eviction_policy is set)
        evict enough of the remaining valid entries to satisfy it.
        Finally run the backend's cleanup().

        A dry run reports the same entries without deleting them. Its
        cleanup report cannot include files that the entry deletions
        would free. Entries whose backing content is missing are dropped
        by the storage even during a dry run, as they hold no data.
        """
        report = PruneReport()
        valid_entries: list[StorageEntryMetadata] = []

        for key in list(self.storage.iter()):
            try:
                entry = self.storage.get_metadata(key)
            except EntryNotFoundError:
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
