from rich.console import Console

_DEFAULT_CONSOLE: Console | None = None


def get_default_console() -> Console:
    """Return the process-wide default Console, creating it on first use.

    Note this forces terminal rendering (``force_terminal=True``) rather
    than letting Rich auto-detect a non-TTY destination -- output will
    include ANSI codes even when redirected to a file or pipe.
    """
    global _DEFAULT_CONSOLE
    if _DEFAULT_CONSOLE is None:
        _DEFAULT_CONSOLE = Console(
            stderr=True, force_terminal=True, color_system="truecolor"
        )
    return _DEFAULT_CONSOLE
