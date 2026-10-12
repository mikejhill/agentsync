"""Structured diagnostics with a stable JSON logging envelope."""

from __future__ import annotations

import logging
from typing import override

from skillsinc.jsonutil import Json


class StructuredFormatter(logging.Formatter):
    """Keep operational diagnostics separate from machine report stdout."""

    @override
    def format(self, record: logging.LogRecord) -> str:
        """Serialize level, logger, timestamp, and formatted diagnostic text."""
        return Json.dumps(
            {
                "version": 1,
                "timestamp": record.created,
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
        ).rstrip()
