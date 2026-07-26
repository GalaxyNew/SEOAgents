"""Unified logging for SEOAgents (L7).

Mirrors the DojoAgents convention: all modules import ``LOGGER`` (or call
``get_logger``) from here.  Raw ``print()``, ad-hoc ``logging.basicConfig()``
and unconfigured standalone loggers are forbidden in project code.
"""
from __future__ import annotations

import logging
import os
import sys

_ROOT_NAME = "seoagents"
_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_configured = False


def _configure_root() -> logging.Logger:
    global _configured
    logger = logging.getLogger(_ROOT_NAME)
    if not _configured:
        level_name = os.environ.get("SEOAGENTS_LOG_LEVEL", "INFO").upper()
        logger.setLevel(getattr(logging, level_name, logging.INFO))
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(logging.Formatter(_FORMAT))
            logger.addHandler(handler)
        logger.propagate = False
        _configured = True
    return logger


LOGGER: logging.Logger = _configure_root()


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger under the unified ``seoagents`` root."""
    _configure_root()
    if not name or name == _ROOT_NAME:
        return LOGGER
    if name.startswith(f"{_ROOT_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_NAME}.{name}")
