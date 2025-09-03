"""Simple logger utilities for the library."""

from __future__ import annotations
import logging
from typing import Optional

LIB_LOGGER_NAME = "afad_quake"

def get_logger() -> logging.Logger:
    """
    Return the library logger. By default it has a NullHandler attached so it won't
    spam user applications unless they opt-in.
    """
    logger = logging.getLogger(LIB_LOGGER_NAME)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger

def configure_logging(level: int = logging.INFO, fmt: Optional[str] = None) -> None:
    """
    Attach a StreamHandler to the library logger for quick visibility.

    Parameters
    ----------
    level : int
        Logging level (e.g., logging.INFO).
    fmt : Optional[str]
        Custom format string. If None, a sensible default is used.

    Examples
    --------
    >>> from logger import configure_logging
    >>> configure_logging()
    >>> # subsequent library calls will emit logs to stdout
    """
    logger = logging.getLogger(LIB_LOGGER_NAME)
    logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(
        fmt or "[%(asctime)s] %(levelname)s %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))

    logger.setLevel(level)
    logger.addHandler(handler)
