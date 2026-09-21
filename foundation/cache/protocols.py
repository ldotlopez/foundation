from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class HasModifiedTime(Protocol):
    """Structural contract for metadata carrying a modification (write)
    time.

    Used by TTLValidator for expiration. Any StorageEntryMetadata
    subclass satisfies this by exposing modified_at, without callers
    needing to import or know about that backend.
    """

    @property
    def modified_at(self) -> float: ...


@runtime_checkable
class HasLastAccessTime(Protocol):
    """Structural contract for metadata carrying a last-access (read)
    time, distinct from modification time.

    Used by eviction policies for LRU ordering - evicting based on
    when an entry was last read, not when it was last written.
    """

    @property
    def last_access_time(self) -> float: ...


@runtime_checkable
class HasSize(Protocol):
    """Structural contract for metadata carrying an entry's size in
    bytes.

    Used by SizeEvictionPolicy to track cache-wide total size without
    needing to know how a given backend computes or stores it.
    """

    @property
    def size(self) -> int: ...


class HasLastAccessTimeAndSize(HasLastAccessTime, HasSize, Protocol):
    """Structural intersection of HasLastAccessTime and HasSize.

    SizeEvictionPolicy needs both: an ordering to decide which entry
    to evict first (last_access_time), and a size to accumulate
    against a byte budget. Not marked runtime_checkable - isinstance
    checks against it aren't needed anywhere; it's used purely as a
    parameter type.
    """
