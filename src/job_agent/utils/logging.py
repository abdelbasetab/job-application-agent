"""Rich-flavored logger so the tracer-bullet run is pleasant to watch."""

from __future__ import annotations

import logging
import sys

from rich.console import Console
from rich.logging import RichHandler

_CONFIGURED = False


def _configure() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    # Force UTF-8 on stdout/stderr so log messages with em-dashes / non-ASCII
    # don't crash on legacy Windows code pages (cp1252).
    for stream in (sys.stdout, sys.stderr):
        try:
            reconfigure = getattr(stream, "reconfigure", None)
            if callable(reconfigure):
                reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    console = Console(stderr=True, force_terminal=True, legacy_windows=False)
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    _configure()
    return logging.getLogger(name)
