import logging
import os
import unittest
from unittest import mock

from foundation.loglib import setup_logger_from_click

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


if __name__ == "__main__":
    unittest.main()
