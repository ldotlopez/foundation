import logging
from dataclasses import dataclass

from rich.console import Console
from rich.logging import RichHandler


@dataclass
class _Context:
    console: Console
    handler: RichHandler


_ctx: _Context | None = None


def setup(root_logger: str | None = None):
    global _ctx
    if _ctx is None:
        console = Console()
        handler = RichHandler(console=console)

        _ctx = _Context(console=Console(), handler=handler)
        logging.basicConfig(handlers=[_ctx.handler])

    logger = logging.getLogger(root_logger)
    logger.setLevel(logging.DEBUG)
