import os

import click
from rich.console import Console

from .consts import DEFAULT_LOG_LEVEL

__all__ = [
    "RICH_DISABLED",
    "RICH_ENABLED",
    "RICH_LOG_HIDE_TIMES",
    "click_logging_options",
    "get_default_console",
    "get_stderr_console",
    "get_stdout_console",
]

_STDOUT_CONSOLE: Console | None = None
_STDERR_CONSOLE: Console | None = None

_no_color = os.environ.get("NO_COLOR", "").lower() in ("1", "true", "yes")
_rich_disabled = os.environ.get("RICH_DISABLED", "").lower() in (
    "1",
    "true",
    "yes",
) or os.environ.get("DISABLE_RICH", "").lower() in ("1", "true", "yes")

RICH_ENABLED = not _no_color and not _rich_disabled
RICH_DISABLED = not RICH_ENABLED

RICH_LOG_HIDE_TIMES = os.environ.get("RICH_LOG_HIDE_TIMES", "").lower() in (
    "1",
    "true",
    "yes",
)


def click_logging_options(f):
    """Reusable logging-related options."""
    f = click.option(
        "--log-level",
        type=str,
        default=DEFAULT_LOG_LEVEL,
        show_default=True,
        help=(
            "Configure Python loggers. Accepts a level (e.g. 'warning') or "
            "rules like 'exiflib:warning,*:info'."
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
