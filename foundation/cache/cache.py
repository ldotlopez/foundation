from __future__ import annotations

import logging
from collections.abc import Iterator

from ..storage import (
    BaseStorage,
    DiskStorage,
    ItemNotFoundError,
    StorageEntryMetadata,
)
from .exc import ExpiredKeyError, MissingKeyError
from .validation import NullValidator, Validator

LOGGER = logging.getLogger(__name__)


class Cache:
    """Thin wrapper that combines storage and validation."""

    def __init__(
        self,
        storage: BaseStorage | None = None,
        validator: Validator | None = None,
    ):
        self.storage = storage or DiskStorage()
        self.validator = validator or NullValidator()

    def set(self, key: str, value: bytes) -> None:
        self.storage.set(key, value)

    def get(self, key: str) -> bytes:
        if not isinstance(self.validator, NullValidator):
            try:
                entry = self.storage.get_metadata(key)
            except ItemNotFoundError as e:
                raise MissingKeyError(key) from e

            if not self.validator.is_valid(entry):
                # Entry is invalid, delete it and raise an error
                self.storage.delete(key)
                raise ExpiredKeyError(key)

        try:
            return self.storage.get(key)
        except ItemNotFoundError as e:
            raise MissingKeyError(key) from e

    def delete(self, key: str) -> None:
        self.storage.delete(key)

    def iter(self) -> Iterator[str]:
        return self.storage.iter()

    def prune(self, *, dry_run: bool = False) -> list[StorageEntryMetadata]:
        """Remove invalid entries according to validator."""
        removed_entries: list[StorageEntryMetadata] = []

        for key in list(self.storage.iter()):
            try:
                entry = self.storage.get_metadata(key)
            except ItemNotFoundError:
                continue

            if not self.validator.is_valid(entry):
                removed_entries.append(entry)

                if not dry_run:
                    self.storage.delete(key)

        return removed_entries
