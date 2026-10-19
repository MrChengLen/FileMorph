# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import logging
from typing import Any

# LogRecord fields that logging sets itself; we don't want to echo them
# back into the serialized payload. Anything NOT in this set that gets
# attached to a record (via `logger.info(..., extra={...})`) is emitted.
_RESERVED_LOG_FIELDS: set[str] = {
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
    "message",
    "module",
    "msecs",
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
}


class JsonLogFormatter(logging.Formatter):
    """One JSON object per log record, with every `extra={...}` field included.

    The earlier format string faked JSON and silently dropped structured
    extras — dashboards and `jq`-based analysis had nothing to filter on.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_FIELDS or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _AccessLogPathOnly(logging.Filter):
    """Drop the query string from uvicorn's access-log line.

    The privacy notice lists the URL path among the logged fields, not the
    query — and a query can carry personal data (email links used to put
    their token there). uvicorn passes the request path as one of
    ``record.args`` and its AccessFormatter unpacks that tuple, so the tuple
    keeps its shape and only the argument that is a path loses its query."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                arg.split("?", 1)[0] if isinstance(arg, str) and arg.startswith("/") else arg
                for arg in record.args
            )
        return True


_ACCESS_LOG_PATH_ONLY = _AccessLogPathOnly()


def configure_logging(debug: bool = False) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        handlers=[handler],
        force=True,
    )
    # addFilter skips an instance that is already attached, so the second
    # call at startup does not stack it.
    logging.getLogger("uvicorn.access").addFilter(_ACCESS_LOG_PATH_ONLY)
