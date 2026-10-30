"""Logging configuration: console or JSON lines, optional rotating file."""

from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path

LOGGER_NAME = "akbench"
_CONSOLE_KEYS = ("asctime", "levelname", "name", "message")


class JsonFormatter(logging.Formatter):
    """One JSON object per line, so logs can be streamed into artifacts."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in getattr(record, "__dict__", {}).items():
            if key.startswith("_") or key in _CONSOLE_KEYS or key in payload:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(
    level: str = "INFO",
    *,
    fmt: str = "console",
    log_file: Path | None = None,
    max_bytes: int = 10_000_000,
    backup_count: int = 5,
) -> logging.Logger:
    """Attach handlers to the ``akbench`` logger and return it.

    Re-running this replaces the previous handlers, which keeps repeated CLI
    invocations (and tests) from duplicating output.
    """
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    logger.setLevel(level.upper())
    logger.propagate = False

    if fmt == "json":
        formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s | %(message)s")

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    if name:
        return logging.getLogger(f"{LOGGER_NAME}.{name}")
    return logging.getLogger(LOGGER_NAME)
