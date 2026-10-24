import io
import logging
import os
import sys
import unittest
from unittest import mock

from rich.logging import RichHandler

from foundation import loglib
from foundation.loglib import setup_logger, setup_logger_from_click

APP = "loglibtestapp"


class LogLevelPrecedenceTests(unittest.TestCase):
    def setUp(self) -> None:
        logging.getLogger(APP).setLevel(logging.NOTSET)

    def level(self, environ: dict[str, str] | None = None, **options: object) -> int:
        with mock.patch.dict(os.environ, environ or {}, clear=True):
            return setup_logger_from_click(APP, infect=False, **options).level

    def test_nothing_set_gives_warning(self) -> None:
        self.assertEqual(self.level(), logging.WARNING)

    def test_env_var_applies(self) -> None:
        self.assertEqual(self.level({"LOGLIBTESTAPP_LOG_LEVEL": "info"}), logging.INFO)

    def test_log_level_beats_env_var(self) -> None:
        environ = {"LOGLIBTESTAPP_LOG_LEVEL": "info"}
        self.assertEqual(self.level(environ, log_level="error"), logging.ERROR)

    def test_verbose_beats_env_var_and_steps_from_warning(self) -> None:
        environ = {"LOGLIBTESTAPP_LOG_LEVEL": "debug"}
        self.assertEqual(self.level(environ, verbose=1), logging.INFO)
        self.assertEqual(self.level(environ, verbose=2), logging.DEBUG)

    def test_verbose_steps_from_log_level(self) -> None:
        self.assertEqual(self.level(log_level="error", verbose=1), logging.WARNING)

    def test_default_log_level_applies_without_cli_or_env(self) -> None:
        self.assertEqual(self.level(default_log_level="info"), logging.INFO)

    def test_env_var_beats_default_log_level(self) -> None:
        environ = {"LOGLIBTESTAPP_LOG_LEVEL": "error"}
        self.assertEqual(self.level(environ, default_log_level="info"), logging.ERROR)

    def test_verbose_ignores_default_log_level(self) -> None:
        self.assertEqual(self.level(default_log_level="error", verbose=1), logging.INFO)


class HandlerChoiceTests(unittest.TestCase):
    def setUp(self) -> None:
        saved = logging.root.handlers[:]
        logging.root.handlers.clear()
        self.addCleanup(setattr, logging.root, "handlers", saved)

    def setup(self, *, stderr_rich: bool) -> logging.Logger:
        with mock.patch.object(loglib, "RICH_STDERR_ENABLED", stderr_rich):
            return setup_logger(APP, log_level="info")

    def test_rich_stderr_gets_rich_handler(self) -> None:
        self.setup(stderr_rich=True)
        self.assertEqual(
            [type(handler) for handler in logging.root.handlers], [RichHandler]
        )

    def test_plain_stderr_gets_one_plain_line_per_record_once(self) -> None:
        logger = self.setup(stderr_rich=False)
        self.setup(stderr_rich=False)
        self.assertEqual(len(logging.root.handlers), 1)
        self.assertNotIsInstance(logging.root.handlers[0], RichHandler)

        # Written to whatever sys.stderr is when the record is emitted.
        with mock.patch.object(sys, "stderr", io.StringIO()) as stderr:
            logger.info("long " * 30)
        line = stderr.getvalue()
        self.assertRegex(line, rf"^\d{{4}}-\d\d-\d\d .* INFO {APP}: (long ){{30}}\n$")


if __name__ == "__main__":
    unittest.main()
