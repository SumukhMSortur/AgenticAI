"""Structured JSON logging with PII-safe filter and contextual correlation."""

import json
import logging
import re
from typing import Any

# Regex patterns for common PII patterns to sanitize from log records
PII_PATTERNS = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Za-z0-9]{11,30}\b"), "[REDACTED_IBAN]"),
    (
        re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b"),
        "[REDACTED_PHONE]",
    ),
    (re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b"), "[REDACTED_CARD]"),
]


class PIISafeFilter(logging.Filter):
    """Filters out any stray PII strings in log messages and record arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern, repl in PII_PATTERNS:
                record.msg = pattern.sub(repl, record.msg)
        if record.args:
            sanitized_args: list[Any] = []
            for arg in record.args if isinstance(record.args, (list, tuple)) else [record.args]:
                if isinstance(arg, str):
                    for pattern, repl in PII_PATTERNS:
                        arg = pattern.sub(repl, arg)
                sanitized_args.append(arg)
            record.args = tuple(sanitized_args)
        return True


class JSONFormatter(logging.Formatter):
    """Formats log records as structured JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "job_id": getattr(record, "job_id", None),
            "thread_id": getattr(record, "thread_id", None),
            "tenant_id": getattr(record, "tenant_id", None),
        }
        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_payload)


def get_logger(name: str) -> logging.Logger:
    """Configures and returns a logger instance with PII filtering and JSON formatting."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        handler.addFilter(PIISafeFilter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
