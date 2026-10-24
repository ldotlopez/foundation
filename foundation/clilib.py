import os
import sys
from typing import TextIO

import click
from rich.console import Console

from .consts import DEFAULT_LOG_LEVEL

__all__ = [
    "RICH_LOG_HIDE_TIMES",
    "RICH_STDERR_DISABLED",
    "RICH_STDERR_ENABLED",
    "RICH_STDOUT_DISABLED",
    "RICH_STDOUT_ENABLED",
    "click_logging_options",
    "get_default_console",
    "get_stderr_console",
    "get_stdout_console",
]

_STDOUT_CONSOLE: Console | None = None
_STDERR_CONSOLE: Console | None = None


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


def _rich_on(stream: TextIO | None) -> bool:
    """Whether rich output suits `stream`: a terminal, rich not disabled
    (`RICH_DISABLED`, `DISABLE_RICH`) and `TERM` not dumb. `NO_COLOR` only
    drops colors, which rich honors by itself."""
    if _env_flag("RICH_DISABLED") or _env_flag("DISABLE_RICH"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return stream is not None and stream.isatty()


# Each stream is rich only when it is a terminal: stdout carries results
# (tables, contents, help), stderr diagnostics (progress, logs).
RICH_STDOUT_ENABLED = _rich_on(sys.stdout)
RICH_STDOUT_DISABLED = not RICH_STDOUT_ENABLED
RICH_STDERR_ENABLED = _rich_on(sys.stderr)
RICH_STDERR_DISABLED = not RICH_STDERR_ENABLED

RICH_LOG_HIDE_TIMES = _env_flag("RICH_LOG_HIDE_TIMES")


def click_logging_options(f):
    """Reusable logging-related options."""
    f = click.option(
        "--log-level",
        type=str,
        default=None,
        help=(
            "Configure Python loggers. Accepts a level (e.g. 'warning') or "
            "rules like 'exiflib:warning,*:info'. Without it (or -v/-q), the "
            f"level comes from <APP>_LOG_LEVEL, else '{DEFAULT_LOG_LEVEL}'."
        ),
    )(f)
    f = click.option(
        "-v",
        "--verbose",
        "verbose",
        count=True,
        help="Increase logging verbosity (can be repeated: -v, -vv, -vvv, etc.)",
    )(f)
    f = click.option(
        "-q",
        "--quiet",
        "quiet",
        count=True,
        help="Decrease logging verbosity (can be repeated: -q, -qq, -qqq, etc.)",
    )(f)
    return f


def get_stdout_console() -> Console:
    """Return the shared Console that writes to stdout, creating it on first use.

    Rich auto-detects the destination: no ANSI codes when it is redirected
    to a file or pipe.
    """
    global _STDOUT_CONSOLE
    if _STDOUT_CONSOLE is None:
        _STDOUT_CONSOLE = Console(
            stderr=False  # , force_terminal=True, color_system="truecolor"
        )

    return _STDOUT_CONSOLE


get_default_console = get_stdout_console


def get_stderr_console() -> Console:
    """Return the shared Console that writes to stderr, creating it on first use.

    Rich auto-detects the destination: no ANSI codes when it is redirected
    to a file or pipe.
    """
    global _STDERR_CONSOLE
    if _STDERR_CONSOLE is None:
        _STDERR_CONSOLE = Console(
            stderr=True  # , force_terminal=True, color_system="truecolor"
        )

    return _STDERR_CONSOLE
