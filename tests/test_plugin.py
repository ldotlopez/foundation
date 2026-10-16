import importlib
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Protocol, runtime_checkable

from foundation.plugin import (
    AlreadyRegisteredError,
    BaseRegister,
    ClassLoader,
    EntryClassConstructionError,
    EntryPointError,
    ModuleLoader,
    NotRegisteredError,
    PluginNotFoundError,
    Register,
)


@runtime_checkable
class ReaderProtocol(Protocol):
    def read(self) -> str: ...


class PluginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.namespace = f"_foundation_test_plugins_{uuid.uuid4().hex}"
        self.package_path = self.root / self.namespace
        self.package_path.mkdir()
        (self.package_path / "__init__.py").write_text("")
        (self.package_path / "contract.py").write_text(
            "from typing import Protocol, runtime_checkable\n"
            "@runtime_checkable\n"
            "class ReaderProtocol(Protocol):\n"
            "    def read(self) -> str: ...\n"
            "class Reader:\n"
            "    def read(self) -> str: return 'value'\n"
        )
        (self.package_path / "reader.py").write_text(
            f"from {self.namespace}.contract import Reader, ReaderProtocol\n"
            "def entry(): return [('primary', ReaderProtocol, Reader())]\n"
            "class Entry:\n"
            "    def __init__(self, value): self.value = value\n"
        )
        (self.package_path / "broken.py").write_text(
            "def entry(): raise RuntimeError('entry failed')\n"
        )
        sys.path.insert(0, str(self.root))
        importlib.invalidate_caches()

    def tearDown(self) -> None:
        sys.path.remove(str(self.root))
        for module_name in list(sys.modules):
            if module_name == self.namespace or module_name.startswith(
                f"{self.namespace}."
            ):
                del sys.modules[module_name]
        self.temporary_directory.cleanup()

    def test_module_discovery_and_missing_plugin(self) -> None:
        loader = ModuleLoader(self.namespace)

        self.assertEqual(loader.discover(), ["broken", "contract", "reader"])
        self.assertEqual(loader.load("reader").__name__, f"{self.namespace}.reader")
        with self.assertRaises(PluginNotFoundError):
            loader.load("unknown")

    def test_class_loader_instantiates_entry_class(self) -> None:
        loader = ClassLoader(self.namespace, "Entry")

        entry = loader.instantiate("reader", "configured")

        self.assertEqual(entry.value, "configured")
        with self.assertRaises(EntryClassConstructionError):
            loader.instantiate("reader")

    def test_base_register_is_transactional_and_rejects_duplicates(self) -> None:
        register = BaseRegister(self.namespace, "entry")

        with self.assertRaises(EntryPointError):
            register.register("broken")
        with self.assertRaises(NotRegisteredError):
            register.get("broken")
        register.register("reader")
        self.assertEqual(len(register.get("reader")), 1)
        with self.assertRaises(AlreadyRegisteredError):
            register.register("reader")

    def test_protocol_register_returns_matching_objects(self) -> None:
        register = Register(self.namespace, "entry")
        register.register("reader")

        results = register.get_by_protocol(ReaderProtocol)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][:2], ("reader", "primary"))
        self.assertEqual(results[0][2].read(), "value")
        self.assertEqual(
            register.get_object("reader", "primary", ReaderProtocol).read(), "value"
        )


if __name__ == "__main__":
    unittest.main()
