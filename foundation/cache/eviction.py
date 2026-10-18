from typing import Protocol

from ..storage import HasLastAccessTime, HasLastAccessTimeAndSize


class EvictionPolicy[M](Protocol):
    """Selects which valid entries to evict when cache-wide limits are exceeded.

    Unlike a Validator, which judges one entry from its own metadata, a
    policy decides over the whole population of valid entries. Cache only
    consults it from prune().
    """

    def select_for_eviction(self, entries: list[M]) -> list[M]:
        """Return the subset of entries to evict."""
        ...


class MaxEntriesEvictionPolicy(EvictionPolicy[HasLastAccessTime]):
    """Evicts the least recently accessed entries beyond max_entries.

    Access time is recorded by reads (get() and get_with_metadata()), so an
    entry that is written but never read keeps its write time.
    """

    def __init__(self, max_entries: int) -> None:
        if max_entries <= 0:
            raise ValueError(f"max_entries must be positive: {max_entries}")
        self.max_entries = max_entries

    def select_for_eviction(
        self, entries: list[HasLastAccessTime]
    ) -> list[HasLastAccessTime]:
        if any(not isinstance(entry, HasLastAccessTime) for entry in entries):
            raise TypeError(
                "MaxEntriesEvictionPolicy requires metadata with last_access_time"
            )

        overflow = len(entries) - self.max_entries
        if overflow <= 0:
            return []
        oldest_first = sorted(entries, key=lambda entry: entry.last_access_time)
        return oldest_first[:overflow]


class SizeEvictionPolicy(EvictionPolicy[HasLastAccessTimeAndSize]):
    """Evicts the least recently accessed entries until the total size of the
    remaining entries is at most max_size_bytes.
    """

    def __init__(self, max_size_bytes: int) -> None:
        if max_size_bytes <= 0:
            raise ValueError(f"max_size_bytes must be positive: {max_size_bytes}")
        self.max_size_bytes = max_size_bytes

    def select_for_eviction(
        self, entries: list[HasLastAccessTimeAndSize]
    ) -> list[HasLastAccessTimeAndSize]:
        if any(not isinstance(entry, HasLastAccessTimeAndSize) for entry in entries):
            raise TypeError(
                "SizeEvictionPolicy requires metadata with last_access_time and size"
            )

        total_size = sum(entry.size for entry in entries)
        to_evict: list[HasLastAccessTimeAndSize] = []
        for entry in sorted(entries, key=lambda entry: entry.last_access_time):
            if total_size <= self.max_size_bytes:
                break
            to_evict.append(entry)
            total_size -= entry.size
        return to_evict
