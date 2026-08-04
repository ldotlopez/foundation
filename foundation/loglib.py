"""Logging setup for foundation-based applications.

Intended usage is a single call at process startup, at the app's
top-level logger name, then forget about it::

    log = setup_logger(__name__)  # or setup_logger("myapp")
    log.info("started")

Everything below that logger (e.g. ``myapp.db``, ``myapp.http``)
propagates up to it automatically via normal ``logging`` propagation,
so most apps never need to call this more than once. Nothing here
touches the true root logger -- the logger you pass in behaves as the
"root" of this setup.

Spec format
-----------
``log_level`` (when given as a string) is a comma-separated list of
``name:level`` pairs.

- ``name`` may be a bare logger name (``"db"``) or ``*``; both mean
  "the app logger passed to setup_logger", i.e. bare/``*`` entries
  never touch the true root logger, only the one you set up. A bare
  word with no dots also matches any logger whose dotted name *ends*
  with that word (so ``"db"`` also matches ``"myapp.storage.db"``).
- ``level`` is one of: debug, info, warning, warn, error, critical, none
  (``none`` suppresses everything, including critical).
- A pair with no ``:`` (just a bare level, e.g. ``"debug"``) sets the
  app logger's own level.
- The app logger always starts at ``warning`` before the spec is
  applied, so specs only need to mention what differs from that.

If ``log_level`` is omitted entirely, it's read from an environment
variable named after the app logger: dots become underscores, the
whole thing uppercased, with ``_LOG_LEVEL`` appended. E.g. a logger
named ``myapp`` looks up ``MYAPP_LOG_LEVEL``; ``myapp.sub`` looks up
``MYAPP_SUB_LOG_LEVEL``. If that variable isn't set either, the
default is ``"warning"``. This env-var lookup only makes sense when
called once at the app's top-level name -- see the module docstring
above.

A plain int (e.g. ``logging.DEBUG``, or ``10``) skips the spec DSL
entirely and just sets the app logger's level directly.
"""

from __future__ import annotations

import argparse
import logging
import os

from rich.console import Console
from rich.logging import RichHandler

from .clilib import get_default_console

LOGGER = logging.getLogger(__name__)

_LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
    "none": logging.CRITICAL + 10,
}

# Ordered quietest -> loudest, used only for -v/-q stepping. Kept separate
# from _LOG_LEVELS because that dict has aliases (warn/warning share a
# value) which would make "move one step" ambiguous.
_VERBOSITY_SCALE = [
    _LOG_LEVELS["none"],
    logging.CRITICAL,
    logging.ERROR,
    logging.WARNING,
    logging.INFO,
    logging.DEBUG,
]


def _env_var_name(logger_name: str) -> str:
    """Build the env-var name for a logger, e.g. "myapp.sub" -> "MYAPP_SUB_LOG_LEVEL"."""
    return logger_name.replace(".", "_").upper() + "_LOG_LEVEL"


def _has_rich_handler(logger: logging.Logger) -> bool:
    """True if this exact logger already has a RichHandler attached."""
    return any(isinstance(handler, RichHandler) for handler in logger.handlers)


def _step_verbosity(level: int, steps: int) -> int:
    """Move `level` by `steps` positions along the quiet<->loud scale, clamped.

    `steps` positive = more verbose (toward DEBUG), negative = quieter
    (toward "none"). The current level is snapped to its closest scale
    entry first, so this also does something sane for a level that
    didn't come from that scale (e.g. an arbitrary custom int).

    Example:
        >>> _step_verbosity(logging.WARNING, steps=2)  # two notches louder
        10  # logging.DEBUG
        >>> _step_verbosity(logging.WARNING, steps=-10)  # clamped at the quiet end
        60  # the "none" pseudo-level
    """
    if steps == 0:
        return level

    closest_index = min(
        range(len(_VERBOSITY_SCALE)),
        key=lambda i: abs(_VERBOSITY_SCALE[i] - level),
    )
    new_index = max(0, min(len(_VERBOSITY_SCALE) - 1, closest_index + steps))
    return _VERBOSITY_SCALE[new_index]


def _apply_verbosity_delta(logger: logging.Logger, verbose: int, quiet: int) -> None:
    """Shift `logger`'s own level by (verbose - quiet) steps, in place. No-op if net zero."""
    steps = verbose - quiet
    if steps:
        logger.setLevel(_step_verbosity(logger.level, steps))


def setup_logger(
    logger: str | logging.Logger,
    console: Console | None = None,
    log_level: str | int | None = None,
    *,
    configure_handler: bool = True,
) -> logging.Logger:
    """Set up one app logger: attach a Rich handler and apply a level/spec.

    Meant to be called exactly once per app, at startup, at the app's
    top-level logger name -- see the module docstring for why. Safe to
    call again for the *same* logger (e.g. accidental double-call): it
    won't attach a second handler, though it will still re-apply
    whatever level/spec you pass.

    Args:
        logger: Either a logger name (``"myapp"``) or an existing
            ``logging.Logger`` instance.
        console: Console to render through. Defaults to the shared
            process-wide console from :func:`get_default_console`.
        log_level: A spec string, a bare level name, a raw int level,
            or None to fall back to an env var (see module docstring).
        configure_handler: If True (default), attach a Rich handler to
            `logger` and set ``logger.propagate = False`` (so records
            aren't also handled further up the hierarchy). Set to
            False to only apply levels, e.g. in tests, headless runs,
            or when something else already owns output for this logger.

    Returns:
        The resolved ``logging.Logger`` (useful as ``log =
        setup_logger(__name__)`` to start using it immediately).

    Examples:
        >>> log = setup_logger("myapp")
        >>> log.info("started")

        With an explicit multi-logger spec::

            >>> setup_logger("myapp", log_level="warning,myapp.db:debug")

        Headless (no Rich, levels only)::

            >>> setup_logger("myapp", log_level="debug", configure_handler=False)
    """
    if isinstance(logger, str):
        logger = logging.getLogger(logger)

    if console is None:
        console = get_default_console()

    if log_level is None:
        log_level = os.environ.get(_env_var_name(logger.name), "warning")

    if configure_handler and not _has_rich_handler(logger):
        logger.addHandler(RichHandler(console=console))
        logger.propagate = False

    if isinstance(log_level, int):
        logger.setLevel(log_level)
    else:
        rules = _parse_rules(log_level, base_name=logger.name)
        _apply_rules(rules)

    return logger


def setup_logger_from_cmdline(
    logger: str | logging.Logger,
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    configure_handler: bool = True,
) -> logging.Logger:
    """setup_logger(), driven by a parsed argparse.Namespace.

    Expects the conventional argparse dest names: ``args.log_level``
    (falling back to :func:`setup_logger`'s normal env-var/default
    behavior if missing or None), and ``args.verbose``/``args.quiet``
    (the counts ``action="count"`` produces for e.g. ``-vvv``), which
    shift *only this app logger's own level* by their net difference.
    Per-logger overrides from the spec (e.g. ``"myapp.db:debug"``) are
    left untouched by -v/-q.

    Args:
        logger: Logger name or instance, as in :func:`setup_logger`.
        args: The parsed ``argparse.Namespace``. Must use ``log_level``,
            ``verbose``, and ``quiet`` as the option dests.
        console: As in :func:`setup_logger`.
        configure_handler: As in :func:`setup_logger`.

    Returns:
        The resolved ``logging.Logger``.

    Example:
        >>> parser = argparse.ArgumentParser()
        >>> parser.add_argument("--log-level")
        >>> parser.add_argument("-v", "--verbose", action="count", default=0)
        >>> parser.add_argument("-q", "--quiet", action="count", default=0)
        >>> args = parser.parse_args()
        >>> log = setup_logger_from_cmdline("myapp", args)
    """
    resolved = setup_logger(
        logger,
        console=console,
        log_level=getattr(args, "log_level", None),
        configure_handler=configure_handler,
    )

    verbose = getattr(args, "verbose", 0) or 0
    quiet = getattr(args, "quiet", 0) or 0
    _apply_verbosity_delta(resolved, verbose, quiet)

    return resolved


def setup_logger_from_click(
    logger: str | logging.Logger,
    *,
    log_level: str | int | None = None,
    verbose: int = 0,
    quiet: int = 0,
    console: Console | None = None,
    configure_handler: bool = True,
) -> logging.Logger:
    """setup_logger(), for Click commands.

    Click callbacks receive option values as plain keyword arguments
    (there's no Namespace object like argparse), so this takes
    `log_level`/`verbose`/`quiet` directly instead of an args object --
    pass through whatever your @click.option-decorated parameters gave
    you.

    Example:
        >>> import click
        >>>
        >>> @click.command()
        ... @click.option("--log-level")
        ... @click.option("-v", "--verbose", count=True)
        ... @click.option("-q", "--quiet", count=True)
        ... def cli(log_level, verbose, quiet):
        ...     log = setup_logger_from_click(
        ...         "myapp", log_level=log_level, verbose=verbose, quiet=quiet
        ...     )
        ...     log.info("started")
    """
    resolved = setup_logger(
        logger,
        console=console,
        log_level=log_level,
        configure_handler=configure_handler,
    )
    _apply_verbosity_delta(resolved, verbose, quiet)
    return resolved


def _resolve_logger_targets(name: str) -> set[str]:
    """Expand a bare (dot-free) logger name to all matching dotted loggers.

    If ``name`` already contains a dot, it's returned as-is (assumed to
    already be a fully-qualified logger name). Otherwise, every
    currently-registered logger whose name ends in ``.{name}`` is added
    too, so e.g. ``"db"`` matches both a logger literally named
    ``"db"`` and one named ``"myapp.storage.db"``.

    Only sees loggers that already exist at call time -- loggers
    created afterward won't retroactively match a bare name from an
    earlier spec application.
    """
    targets = {name}
    if "." in name:
        return targets

    suffix = f".{name}"
    for logger_name, logger_obj in logging.root.manager.loggerDict.items():
        if isinstance(logger_obj, logging.PlaceHolder):
            continue
        if logger_name.endswith(suffix):
            targets.add(logger_name)

    return targets


def _normalize_pair(pair: str) -> tuple[str, str]:
    """Split a single ``name:level`` spec entry into ``(name, level)``.

    A pair with no ``:`` is treated as a bare level applying to ``*``.
    """
    if ":" not in pair:
        return "*", pair

    name, level = pair.split(":", 1)
    return name.strip(), level.strip()


def _parse_rules(spec: str, base_name: str) -> list[tuple[str, int]]:
    """Parse a spec string into an ordered list of (logger_name, level) rules.

    Always starts with ``(base_name, WARNING)`` as the baseline. Bare
    entries and ``*`` both resolve to `base_name` (the app logger),
    never the true root logger. Invalid entries (unknown level name,
    or an empty logger name before a ``:``) are logged as a warning
    and skipped rather than raising.

    Rules are applied in order by :func:`_apply_rules`, so later
    entries for the same logger override earlier ones.
    """
    rules: list[tuple[str, int]] = [(base_name, _LOG_LEVELS["warning"])]

    for pair_raw in spec.split(","):
        pair = pair_raw.strip()
        if not pair:
            continue

        name, level = _normalize_pair(pair)
        level_name = level.lower()

        if not level_name or level_name not in _LOG_LEVELS:
            LOGGER.warning("invalid pair '%s' in spec '%s'", pair_raw, spec)
            continue

        level = _LOG_LEVELS[level_name]

        if name == "*":
            rules.append((base_name, level))
            continue

        if not name:
            LOGGER.warning("invalid pair '%s' in spec '%s'", pair_raw, spec)
            continue

        for logger_name in _resolve_logger_targets(name):
            rules.append((logger_name, level))

    return rules


def _apply_rules(rules: list[tuple[str, int]]) -> None:
    """Apply parsed (logger_name, level) rules via logging.getLogger(...).setLevel.

    Rules are applied in list order, so if the same logger appears
    twice, the last one wins.
    """
    for logger_name, level in rules:
        logging.getLogger(logger_name).setLevel(level)


__all__ = [
    "setup_logger",
    "setup_logger_from_cmdline",
    "setup_logger_from_click",
]
