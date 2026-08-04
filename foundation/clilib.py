import os

import click
from rich.console import Console

_DEFAULT_CONSOLE: Console | None = None

_no_color = os.environ.get("NO_COLOR", "").lower() in ("1", "true", "yes")
_rich_disabled = os.environ.get("RICH_DISABLED", "").lower() in (
    "1",
    "true",
    "yes",
) or os.environ.get("DISABLE_RICH", "").lower() in ("1", "true", "yes")

RICH_ENABLED = not _no_color and not _rich_disabled
RICH_DISABLED = not RICH_ENABLED


def click_logging_options(f):
    """Reusable logging-related options."""
    f = click.option(
        "--log-level",
        type=str,
        default="warning",
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


def get_default_console() -> Console:
    """Return the process-wide default Console, creating it on first use.

    Note this forces terminal rendering (``force_terminal=True``) rather
    than letting Rich auto-detect a non-TTY destination -- output will
    include ANSI codes even when redirected to a file or pipe.
    """
    global _DEFAULT_CONSOLE
    if _DEFAULT_CONSOLE is None:
        _DEFAULT_CONSOLE = Console(
            stderr=True  # , force_terminal=True, color_system="truecolor"
        )

    return _DEFAULT_CONSOLE
