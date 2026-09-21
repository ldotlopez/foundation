from __future__ import annotations

from abc import abstractmethod

from .protocols import HasLastAccessTime, HasLastAccessTimeAndSize


class EvictionPolicy[M]:
    """Base class for cache-wide eviction policies.

    Deliberately separate from Validator[T]. A Validator answers "is
    this single entry still valid" from that entry's own metadata
    alone - a pure per-entry function. An EvictionPolicy answers "of
    all currently-valid entries, which should be evicted" - a
    population-level decision no single entry's metadata can answer
    by itself. Folding this into Validator would mean either passing
    the whole population into every single-entry check, or narrowing
    is_valid's signature on override - the same Liskov problem
    TTLValidator hit and was fixed for. Kept as its own hierarchy on
    purpose.

    Only consulted from Cache.prune() (directly, or self-triggered
    from Cache.set() every eviction_check_interval writes) - not from
    Cache.get(). A single read has no cheap way to know whether the
    whole cache is over budget.
    """

    @abstractmethod
    def select_for_eviction(self, entries: list[M]) -> list[M]:
        """Given all currently-valid entries, return the subset that
        should be evicted."""
        ...


class MaxEntriesEvictionPolicy(EvictionPolicy[HasLastAccessTime]):
    """Evicts the least-recently-accessed entries once the cache
    holds more than max_entries.

    Ordering is by last_access_time - true LRU, based on when an
    entry was last read, not modified_at (when it was last written).
    This only stays meaningful for entries read via
    Cache.get()/BaseStorage.get_and_touch(): an entry that's only
    ever set() and never read keeps last_access_time frozen at its
    write time, and reads that bypass Cache.get() (calling a
    storage backend's get() directly) don't update it either.
    """

    def __init__(self, max_entries: int):
        self.max_entries = max_entries

    def select_for_eviction(
        self, entries: list[HasLastAccessTime]
    ) -> list[HasLastAccessTime]:
        overflow = len(entries) - self.max_entries
        if overflow <= 0:
            return []

        oldest_first = sorted(entries, key=lambda e: e.last_access_time)
        return oldest_first[:overflow]


class SizeEvictionPolicy(EvictionPolicy[HasLastAccessTimeAndSize]):
    """Evicts the least-recently-accessed entries until total size is
    back under max_size_bytes.

    Same LRU-by-last-access ordering and the same caveat as
    MaxEntriesEvictionPolicy: only meaningful for entries actually
    read through Cache.get().
    """

    def __init__(self, max_size_bytes: int):
        self.max_size_bytes = max_size_bytes

    def select_for_eviction(
        self, entries: list[HasLastAccessTimeAndSize]
    ) -> list[HasLastAccessTimeAndSize]:
        total_size = sum(e.size for e in entries)
        if total_size <= self.max_size_bytes:
            return []

        oldest_first = sorted(entries, key=lambda e: e.last_access_time)
        to_evict: list[HasLastAccessTimeAndSize] = []
        for entry in oldest_first:
            if total_size <= self.max_size_bytes:
                break
            to_evict.append(entry)
            total_size -= entry.size

        return to_evict
