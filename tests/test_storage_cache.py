import tempfile
import unittest
from pathlib import Path

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
    SqliteStorage,
    StorageEntryMetadata,
)


class RejectKeyValidator(Validator[StorageEntryMetadata]):
    def is_valid(self, metadata: StorageEntryMetadata) -> bool:
        return metadata.key != "expired"


class StorageTests(unittest.TestCase):
    def test_disk_storage_round_trip_metadata_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = DiskStorage(Path(temporary_directory))
            storage.set("first-key", b"value")
            metadata_before = storage.get_metadata("first-key")

            self.assertEqual(storage.get("first-key"), b"value")
            self.assertIn("first-key", list(storage.iter()))
            self.assertEqual(storage.get_metadata("first-key").size, 5)
            value, accessed_metadata = storage.get_with_metadata("first-key")
            self.assertEqual(value, b"value")
            self.assertGreaterEqual(
                accessed_metadata.last_access_time,
                metadata_before.last_access_time,
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

    def test_eviction_policy_rejects_incompatible_metadata_at_runtime(self) -> None:
        class StorageWithoutAccessTime(DiskStorage):
            def get_metadata(self, key: str) -> StorageEntryMetadata:
                return StorageEntryMetadata(key=key)

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache = Cache(
                storage=StorageWithoutAccessTime(Path(temporary_directory)),
                eviction_policy=MaxEntriesEvictionPolicy(max_entries=1),
            )
            cache.set("key", b"value")

            with self.assertRaisesRegex(TypeError, "last_access_time"):
                cache.prune()

        class StorageWithoutSize(DiskStorage):
            def get_metadata(self, key: str) -> StorageEntryMetadata:
                return StorageEntryMetadata(key=key)

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache = Cache(
                storage=StorageWithoutSize(Path(temporary_directory)),
                eviction_policy=SizeEvictionPolicy(max_size_bytes=1),
            )
            cache.set("key", b"value")

            with self.assertRaisesRegex(TypeError, "last_access_time and size"):
                cache.prune()

    def test_ttl_rejects_incompatible_metadata_at_runtime(self) -> None:
        class StorageWithoutModificationTime(DiskStorage):
            def get_metadata(self, key: str) -> StorageEntryMetadata:
                return StorageEntryMetadata(key=key)

            def get_with_metadata(self, key: str) -> tuple[bytes, StorageEntryMetadata]:
                return self.get(key), self.get_metadata(key)

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache = Cache(
                storage=StorageWithoutModificationTime(Path(temporary_directory)),
                validator=TTLValidator(expiration_time=60),
            )
            cache.set("key", b"value")

            with self.assertRaisesRegex(TypeError, "modified_at"):
                cache.get("key")

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
