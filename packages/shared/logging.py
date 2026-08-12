"""Stdlib logging configuration — no new dependency for something `logging` already does."""

import logging
import sys

from packages.shared.config import settings

_CONFIGURED = False


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    _CONFIGURED = True
