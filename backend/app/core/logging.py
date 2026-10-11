"""Structured-ish logging. Never pass secrets to these loggers."""

from __future__ import annotations

import json
import logging
import sys
import time
from contextlib import contextmanager


class _KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} {record.name}: {record.getMessage()}"
        extra = getattr(record, "fields", None)
        if extra:
            base += " " + json.dumps(extra, ensure_ascii=False, default=str)
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_KeyValueFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Third-party HTTP clients can log request URLs containing API keys (e.g. ?key=...).
    for noisy in ("httpx", "httpx2", "httpcore", "anthropic", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, msg: str, **fields) -> None:
    logger.info(msg, extra={"fields": fields})


@contextmanager
def timer():
    """Usage: `with timer() as t: ...; t()` -> elapsed milliseconds."""
    start = time.perf_counter()
    elapsed = {"ms": None}

    def get() -> float:
        return elapsed["ms"] if elapsed["ms"] is not None else (time.perf_counter() - start) * 1000

    try:
        yield get
    finally:
        elapsed["ms"] = round((time.perf_counter() - start) * 1000, 1)
