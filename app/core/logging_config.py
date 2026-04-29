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


def configure_logging(debug: bool = False) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        handlers=[handler],
        force=True,
    )
