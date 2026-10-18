import tempfile
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

from foundation.cache import (
    Cache,
    ExpiredKeyError,
    MaxEntriesEvictionPolicy,
    MissingKeyError,
    NullValidator,
    SizeEvictionPolicy,
    TTLValidator,
    Validator,
)
from foundation.storage import (
    DiskStorage,
    EntryNotFoundError,
    HasCreatedTime,
    HasLastAccessTime,
    HasModifiedTime,
    HasSize,
    KeyHashStorage,
    SqliteStorage,
    StorageEntryMetadata,
    ValueHashStorage,
)


class RejectKeyValidator(Validator[StorageEntryMetadata]):
    def is_valid(self, metadata: StorageEntryMetadata) -> bool:
        return metadata.key != "expired"


@dataclass(frozen=True)
class KeyOnlyMetadata:
    key: str


class StorageTests(unittest.TestCase):
    def test_disk_storage_round_trip_metadata_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = DiskStorage(Path(temporary_directory))
            storage.set("first-key", b"value")
            metadata_before = storage.get_metadata("first-key")
            self.assertIsInstance(metadata_before, StorageEntryMetadata)
            self.assertIsInstance(metadata_before, HasCreatedTime)
            self.assertIsInstance(metadata_before, HasModifiedTime)
            self.assertIsInstance(metadata_before, HasLastAccessTime)
            self.assertIsInstance(metadata_before, HasSize)

            self.assertEqual(storage.get("first-key"), b"value")
            self.assertIn("first-key", list(storage.iter()))
            self.assertEqual(storage.get_metadata("first-key").size, 5)
            storage.set("first-key", b"updated")
            metadata_after_write = storage.get_metadata("first-key")
            self.assertEqual(
                metadata_after_write.created_at, metadata_before.created_at
            )
            self.assertEqual(metadata_after_write.size, len(b"updated"))
            value, accessed_metadata = storage.get_with_metadata("first-key")
            self.assertEqual(value, b"updated")
            self.assertGreaterEqual(
                accessed_metadata.last_access_time,
                metadata_after_write.last_access_time,
            )
            with self.assertRaises(EntryNotFoundError):
                storage.get("missing")

            storage.delete("first-key")
            self.assertEqual(
                storage.cleanup(dry_run=True), [str(Path(temporary_directory) / "fi")]
            )
            self.assertTrue((Path(temporary_directory) / "fi").exists())
            storage.cleanup()
            self.assertFalse((Path(temporary_directory) / "fi").exists())

    def test_disk_storage_rejects_unsafe_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = DiskStorage(Path(temporary_directory))
            for key in ("", "../escape", "a/b", "a\\b", ".", ".."):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    storage.set(key, b"value")

    def test_sqlite_storage_round_trip_and_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "cache.sqlite3"
            storage = SqliteStorage(db_path)
            storage.set("key", b"value")
            metadata_before = storage.get_metadata("key")
            value, metadata = storage.get_with_metadata("key")

            self.assertEqual(value, b"value")
            self.assertEqual(metadata.size, 5)
            self.assertGreaterEqual(
                metadata.last_access_time, metadata_before.last_access_time
            )
            self.assertIn("key", list(storage.iter()))
            storage.close()

            reopened = SqliteStorage(db_path)
            self.assertEqual(reopened.get("key"), b"value")
            reopened.delete("key")
            self.assertEqual(list(reopened.iter()), [])
            reopened.close()

    def test_disk_storage_ignores_unindexed_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = DiskStorage(Path(temporary_directory))
            storage.set("indexed", b"value")
            (Path(temporary_directory) / "in" / "tmpleftover").write_bytes(b"junk")
            (Path(temporary_directory) / "ex").mkdir()
            (Path(temporary_directory) / "ex" / "external").write_bytes(b"junk")

            self.assertEqual(list(storage.iter()), ["indexed"])
            with self.assertRaises(EntryNotFoundError):
                storage.get("external")
            storage.close()

    def test_get_records_access_time_in_every_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            backends = [
                DiskStorage(base_dir / "disk"),
                KeyHashStorage(base_dir / "key-hash"),
                ValueHashStorage(base_dir / "value-hash"),
                SqliteStorage(base_dir / "sqlite.sqlite3"),
            ]
            for storage in backends:
                with self.subTest(backend=type(storage).__name__):
                    storage.set("key", b"value")
                    written_at = storage.get_metadata("key").last_access_time
                    with mock.patch(
                        f"{type(storage).__module__}.now_utc_ts",
                        return_value=written_at + 60,
                    ):
                        self.assertEqual(storage.get("key"), b"value")
                    self.assertEqual(
                        storage.get_metadata("key").last_access_time, written_at + 60
                    )
                    storage.close()

    def test_cleanup_interval_runs_cleanup_once_when_due(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            factories = {
                DiskStorage: lambda: DiskStorage(
                    base_dir / "disk", cleanup_interval=60
                ),
                KeyHashStorage: lambda: KeyHashStorage(
                    base_dir / "key-hash", cleanup_interval=60
                ),
                ValueHashStorage: lambda: ValueHashStorage(
                    base_dir / "value-hash", cleanup_interval=60
                ),
                SqliteStorage: lambda: SqliteStorage(
                    base_dir / "sqlite.sqlite3", cleanup_interval=60
                ),
            }
            for storage_class, open_storage in factories.items():
                with (
                    self.subTest(backend=storage_class.__name__),
                    mock.patch.object(
                        storage_class, "cleanup", return_value=[]
                    ) as cleanup,
                ):
                    open_storage().close()
                    open_storage().close()
                    cleanup.assert_not_called()

                    with mock.patch(
                        f"{storage_class.__module__}.now_utc_ts",
                        return_value=time.time() + 120,
                    ):
                        open_storage().close()
                        open_storage().close()
                    cleanup.assert_called_once()

    def test_close_removes_owned_temporary_directory(self) -> None:
        for storage_class in (DiskStorage, KeyHashStorage, ValueHashStorage):
            with self.subTest(backend=storage_class.__name__):
                storage = storage_class()
                storage.set("key", b"value")
                self.assertTrue(storage.base_dir.exists())
                storage.close()
                self.assertFalse(storage.base_dir.exists())

    def test_close_keeps_caller_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = DiskStorage(Path(temporary_directory))
            storage.set("key", b"value")
            storage.close()
            self.assertTrue(Path(temporary_directory, "ke", "key").exists())

    def test_entry_not_found_error_message_names_the_key(self) -> None:
        self.assertEqual(str(EntryNotFoundError("key")), "key")


class CacheTests(unittest.TestCase):
    def test_get_maps_missing_key_and_removes_expired_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache = Cache(
                storage=DiskStorage(Path(temporary_directory)),
                validator=RejectKeyValidator(),
            )

            with self.assertRaises(MissingKeyError):
                cache.get("missing")
            cache.set("expired", b"old")
            with self.assertRaises(ExpiredKeyError):
                cache.get("expired")
            self.assertNotIn("expired", list(cache.iter()))

    def test_prune_dry_run_then_removes_invalid_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = DiskStorage(Path(temporary_directory))
            cache = Cache(storage=storage, validator=RejectKeyValidator())
            cache.set("expired", b"old")
            cache.set("current", b"new")

            dry_run_entries = cache.prune(dry_run=True)
            self.assertEqual([entry.key for entry in dry_run_entries], ["expired"])
            self.assertCountEqual(list(cache.iter()), ["expired", "current"])

            removed_entries = cache.prune()
            self.assertEqual([entry.key for entry in removed_entries], ["expired"])
            self.assertEqual(list(cache.iter()), ["current"])

    def test_prune_runs_storage_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = DiskStorage(Path(temporary_directory))
            cache = Cache(storage=storage, validator=RejectKeyValidator())
            cache.set("expired", b"old")
            shard_dir = Path(temporary_directory) / "ex"

            cache.prune(dry_run=True)
            self.assertTrue(shard_dir.exists())
            cache.prune()
            self.assertFalse(shard_dir.exists())
            storage.close()

    def test_corrupt_entry_is_a_miss_and_prune_removes_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = DiskStorage(Path(temporary_directory))
            cache = Cache(storage=storage)
            cache.set("broken", b"value")
            cache.set("pruned", b"value")
            cache.set("healthy", b"value")
            (Path(temporary_directory) / "br" / "broken").unlink()
            (Path(temporary_directory) / "pr" / "pruned").unlink()

            with self.assertRaises(MissingKeyError):
                cache.get("broken")
            self.assertEqual(cache.prune(dry_run=True), [])
            self.assertIn("pruned", list(cache.iter()))
            self.assertEqual(cache.prune(), [])
            self.assertEqual(list(cache.iter()), ["healthy"])
            cache.close()

    def test_close_closes_storage(self) -> None:
        storage = mock.Mock()
        Cache(storage=storage).close()
        storage.close.assert_called_once_with()

    def test_rejects_non_positive_limits(self) -> None:
        constructors = {
            "max_entries": lambda: MaxEntriesEvictionPolicy(max_entries=0),
            "max_size_bytes": lambda: SizeEvictionPolicy(max_size_bytes=-1),
            "expiration_time": lambda: TTLValidator(expiration_time=0),
            "eviction_check_interval": lambda: Cache(
                storage=mock.Mock(), eviction_check_interval=0
            ),
        }
        for name, construct in constructors.items():
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, name):
                construct()

    def test_set_periodically_applies_max_entries_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache = Cache(
                storage=DiskStorage(Path(temporary_directory)),
                validator=NullValidator(),
                eviction_policy=MaxEntriesEvictionPolicy(max_entries=1),
                eviction_check_interval=1,
            )
            cache.set("first", b"one")
            cache.set("second", b"two")

            self.assertEqual(len(list(cache.iter())), 1)

    def test_storage_metadata_contract_is_key_only_and_capabilities_are_optional(
        self,
    ) -> None:
        metadata = KeyOnlyMetadata("key")

        self.assertIsInstance(metadata, StorageEntryMetadata)
        self.assertNotIsInstance(metadata, HasCreatedTime)
        self.assertNotIsInstance(metadata, HasModifiedTime)
        self.assertNotIsInstance(metadata, HasLastAccessTime)
        self.assertNotIsInstance(metadata, HasSize)

    def test_cache_policies_raise_for_missing_metadata_capabilities(self) -> None:
        metadata = KeyOnlyMetadata("key")
        count_policy = MaxEntriesEvictionPolicy(max_entries=1)
        size_policy = SizeEvictionPolicy(max_size_bytes=10)

        with self.assertRaisesRegex(TypeError, "last_access_time"):
            count_policy.select_for_eviction([metadata])
        with self.assertRaisesRegex(TypeError, "last_access_time and size"):
            size_policy.select_for_eviction([metadata])

    def test_ttl_validator_raises_for_missing_modified_time(self) -> None:
        with self.assertRaisesRegex(TypeError, "modified_at"):
            TTLValidator(expiration_time=60).is_valid(KeyOnlyMetadata("key"))

    def test_cache_get_updates_lru_access_time(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = SqliteStorage(Path(temporary_directory) / "cache.sqlite3")
            cache = Cache(
                storage=storage,
                eviction_policy=MaxEntriesEvictionPolicy(max_entries=1),
            )
            cache.set("old", b"old")
            cache.set("new", b"new")

            self.assertEqual(cache.get("old"), b"old")
            removed_entries = cache.prune()

            self.assertEqual([entry.key for entry in removed_entries], ["new"])
            self.assertEqual(list(cache.iter()), ["old"])
            storage.close()

    def test_eviction_policies_select_lru_entries(self) -> None:
        class Entry:
            def __init__(self, key: str, accessed: int, size: int):
                self.key = key
                self.last_access_time = accessed
                self.size = size

        entries = [Entry("old", 1, 4), Entry("middle", 2, 3), Entry("new", 3, 2)]
        count_evictions = MaxEntriesEvictionPolicy(max_entries=2)
        size_evictions = SizeEvictionPolicy(max_size_bytes=4)

        self.assertEqual(
            [entry.key for entry in count_evictions.select_for_eviction(entries)],
            ["old"],
        )
        self.assertEqual(
            [entry.key for entry in size_evictions.select_for_eviction(entries)],
            ["old", "middle"],
        )


if __name__ == "__main__":
    unittest.main()
