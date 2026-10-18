import hashlib
import tempfile
import unittest
from pathlib import Path

from foundation.storage import (
    EntryNotFoundError,
    KeyHashStorage,
    StorageCorruptionError,
    ValueHashStorage,
)


class HashedStorageTests(unittest.TestCase):
    def test_key_hash_storage_supports_arbitrary_keys_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = KeyHashStorage(Path(temporary_directory))
            key = "../strange/ключ"

            storage.set(key, b"first")
            initial_metadata = storage.get_metadata(key)
            storage.set(key, b"updated value")
            updated_metadata = storage.get_metadata(key)

            self.assertEqual(storage.get(key), b"updated value")
            self.assertEqual(list(storage.iter()), [key])
            self.assertEqual(updated_metadata.created_at, initial_metadata.created_at)
            self.assertGreaterEqual(
                updated_metadata.modified_at, initial_metadata.modified_at
            )
            self.assertEqual(updated_metadata.size, len(b"updated value"))
            self.assertEqual(
                storage._object_path(hashlib.sha256(key.encode()).hexdigest()).name,
                hashlib.sha256(key.encode()).hexdigest(),
            )
            storage.delete(key)
            self.assertEqual(list(storage.iter()), [])
            storage.close()

    def test_key_hash_storage_persists_metadata_after_close(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            storage = KeyHashStorage(base_dir)
            storage.set("key", b"value")
            storage.close()

            reopened = KeyHashStorage(base_dir)
            self.assertEqual(reopened.get("key"), b"value")
            self.assertEqual(list(reopened.iter()), ["key"])
            reopened.close()

    def test_value_hash_storage_deduplicates_and_preserves_referenced_blobs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = ValueHashStorage(Path(temporary_directory))
            storage.set("one", b"shared")
            storage.set("two", b"shared")
            shared_path = storage._object_path(hashlib.sha256(b"shared").hexdigest())

            storage.delete("one")
            self.assertTrue(shared_path.exists())
            self.assertEqual(storage.get("two"), b"shared")

            storage.set("two", b"replacement")
            self.assertFalse(shared_path.exists())
            self.assertEqual(storage.get("two"), b"replacement")
            self.assertEqual(storage.get_metadata("two").size, len(b"replacement"))
            storage.close()

    def test_hash_stores_distinguish_missing_keys_from_missing_objects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = KeyHashStorage(Path(temporary_directory))
            with self.assertRaises(EntryNotFoundError):
                storage.get("missing")

            storage.set("present", b"value")
            object_path = storage._object_path(hashlib.sha256(b"present").hexdigest())
            object_path.unlink()
            with self.assertRaises(StorageCorruptionError):
                storage.get("present")
            storage.close()

    def test_value_hash_storage_detects_modified_blob(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = ValueHashStorage(Path(temporary_directory))
            storage.set("key", b"value")
            object_path = storage._object_path(hashlib.sha256(b"value").hexdigest())
            object_path.write_bytes(b"tampered")

            with self.assertRaises(StorageCorruptionError):
                storage.get("key")
            storage.close()


if __name__ == "__main__":
    unittest.main()
