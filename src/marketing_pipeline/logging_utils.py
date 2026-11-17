"""Logging setup: run-scoped context, optional JSON output and secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone

from .secrets import registered_secret_values

_RUN_CONTEXT: dict[str, str] = {}

# Catch credentials even if they never passed through ``Secret`` (e.g. echoed
# back inside a third-party error message or a URL).
_PATTERNS = [
    re.compile(r"(?i)(access_token|refresh_token|client_secret|developer[-_]token|api[-_]?key)"
               r"(\"?\s*[=:]\s*\"?)([^\s\"&,}]+)"),
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._\-]{8,})"),
]
_MASK = "********"


def redact(text: str) -> str:
    for value in registered_secret_values():
        text = text.replace(value, _MASK)
    text = _PATTERNS[0].sub(lambda m: f"{m.group(1)}{m.group(2)}{_MASK}", text)
    text = _PATTERNS[1].sub(lambda m: f"{m.group(1)}{_MASK}", text)
    return text


def set_run_context(**fields: str) -> None:
    """Attach fields (run_id, mode, ...) to every subsequent log record."""
    _RUN_CONTEXT.update(fields)


class _ContextRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        record.run_id = _RUN_CONTEXT.get("run_id", "-")
        if record.exc_info and record.exc_info[1] is not None:
            # Format now so the traceback text is redacted too.
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **_RUN_CONTEXT,
        }
        payload.update(getattr(record, "fields", {}))
        if record.exc_text:
            payload["exception"] = record.exc_text
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(_ContextRedactionFilter())
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s [%(run_id)s] %(name)s: %(message)s")
        )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"marketing_pipeline.{name}")
