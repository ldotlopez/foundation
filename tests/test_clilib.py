import importlib
import io
import os
import sys
import unittest
from unittest import mock

from foundation import clilib


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


class RichPerStreamTests(unittest.TestCase):
    """The RICH_STD* values are computed at import: reload with a patched
    environment and streams."""

    def tearDown(self) -> None:
        importlib.reload(clilib)

    def reload(
        self, environ: dict[str, str], *, stdout_tty: bool, stderr_tty: bool
    ) -> None:
        stdout = _Terminal() if stdout_tty else io.StringIO()
        stderr = _Terminal() if stderr_tty else io.StringIO()
        with (
            mock.patch.dict(os.environ, environ, clear=True),
            mock.patch.object(sys, "stdout", stdout),
            mock.patch.object(sys, "stderr", stderr),
        ):
            importlib.reload(clilib)

    def test_each_stream_follows_its_own_terminal(self) -> None:
        self.reload({}, stdout_tty=True, stderr_tty=False)
        self.assertTrue(clilib.RICH_STDOUT_ENABLED)
        self.assertTrue(clilib.RICH_STDERR_DISABLED)

        self.reload({}, stdout_tty=False, stderr_tty=True)
        self.assertTrue(clilib.RICH_STDOUT_DISABLED)
        self.assertTrue(clilib.RICH_STDERR_ENABLED)

    def test_env_vars_and_dumb_terminal_disable_both(self) -> None:
        for environ in (
            {"DISABLE_RICH": "1"},
            {"RICH_DISABLED": "true"},
            {"TERM": "dumb"},
        ):
            with self.subTest(environ=environ):
                self.reload(environ, stdout_tty=True, stderr_tty=True)
                self.assertTrue(clilib.RICH_STDOUT_DISABLED)
                self.assertTrue(clilib.RICH_STDERR_DISABLED)

    def test_no_color_keeps_rich(self) -> None:
        self.reload({"NO_COLOR": "1"}, stdout_tty=True, stderr_tty=True)
        self.assertTrue(clilib.RICH_STDOUT_ENABLED)
        self.assertTrue(clilib.RICH_STDERR_ENABLED)


if __name__ == "__main__":
    unittest.main()
