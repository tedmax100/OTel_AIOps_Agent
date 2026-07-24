"""Stdout JSON logger.

Under zero-code instrumentation (`opentelemetry-instrument ...`), the OTel
distro attaches its own LoggingHandler to the root logger and ships records
out via OTLP. This module's job is the *other* sink: a structured JSON line
on stdout for `docker logs` / `kubectl logs` debuggability.

The handler reads `OTEL_SERVICE_NAME`, `GIT_REPO`, `GIT_VERSION` from the
environment so the schema is consistent with what zero-code sends via OTLP.
Application code emits records with `log_event(...)` so the `event` field
is always a `BizEvent` enum value.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace

from .events import BizEvent

_SCHEMA_KEYS = {"event", "git_repo", "git_version", "service"}


class _JsonFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__()
        self._service = os.environ.get("OTEL_SERVICE_NAME", "unknown")
        self._git_repo = os.environ.get("GIT_REPO", "unknown/unknown")
        self._git_version = os.environ.get("GIT_VERSION", "v0.0.0")

    def format(self, record: logging.LogRecord) -> str:
        span_ctx = trace.get_current_span().get_span_context()
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "service": self._service,
            "git_repo": self._git_repo,
            "git_version": self._git_version,
            "msg": record.getMessage(),
        }

        if span_ctx.is_valid:
            payload["trace_id"] = format(span_ctx.trace_id, "032x")
            payload["span_id"] = format(span_ctx.span_id, "016x")

        for key, value in record.__dict__.items():
            if key in {
                "args",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
                "taskName",
                # Don't double-write fields that OTLP logging adds:
                "otelSpanID",
                "otelTraceID",
                "otelServiceName",
                "otelTraceSampled",
            }:
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def setup_stdout_json_logging(level: str = "INFO") -> None:
    """Attach a JSON formatter to the root logger's stdout. The OTel distro's
    own LoggingHandler is still attached separately (zero-code does that)."""
    root = logging.getLogger()

    # Remove any pre-existing stdout StreamHandlers — keep handlers added by
    # zero-code (OTLP LoggingHandler, etc.).
    for h in list(root.handlers):
        if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) in (
            sys.stdout,
            sys.stderr,
        ):
            root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    event: BizEvent,
    message: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit a biz event log line. The `event` value becomes a log attribute
    that flows out via OTLP to Loki as structured metadata — and into the
    stdout JSON. Always pass a BizEvent member, never a free-form string."""
    if any(k in _SCHEMA_KEYS for k in fields):
        raise ValueError(f"fields collide with schema keys: {_SCHEMA_KEYS & fields.keys()}")
    logger.log(level, message, extra={"event": event.value, **fields})
