# SPDX-License-Identifier: AGPL-3.0-or-later
import errno
import json
import logging
import traceback
from typing import Any

# LogRecord fields that logging sets itself; we don't want to echo them
# back into the serialized payload. Anything NOT in this set that gets
# attached to a record (via `logger.info(..., extra={...})`) is emitted.
_RESERVED_LOG_FIELDS: set[str] = {
    "args",
    "color_message",
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


def _type_name(exc: BaseException) -> str:
    kind = type(exc)
    name = (
        kind.__qualname__
        if kind.__module__ == "builtins"
        else f"{kind.__module__}.{kind.__qualname__}"
    )
    if isinstance(exc, OSError) and exc.errno in errno.errorcode:
        name += f" [{errno.errorcode[exc.errno]}]"
    if isinstance(exc, BaseExceptionGroup):
        name += " (" + ", ".join(_type_name(sub) for sub in exc.exceptions) + ")"
    return name


def _exception_without_text(exc: BaseException | None) -> str:
    """The traceback of ``exc`` and its chain with each exception's type but
    not its text: a library's error message can quote the uploaded file, and
    the privacy notice says no file content is logged. The frames show our
    own source lines, never data."""
    parts: list[str] = []
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        frames = "".join(traceback.format_tb(exc.__traceback__))
        parts.append(f"Traceback (most recent call last):\n{frames}{_type_name(exc)}")
        if exc.__cause__ is not None:
            parts.append("The above exception was the direct cause of the following exception:")
            exc = exc.__cause__
        elif exc.__context__ is not None and not exc.__suppress_context__:
            parts.append("During handling of the above exception, another exception occurred:")
            exc = exc.__context__
        else:
            exc = None
    return "\n\n".join(reversed(parts))


class JsonLogFormatter(logging.Formatter):
    """One JSON object per log record, with every `extra={...}` field included.

    The earlier format string faked JSON and silently dropped structured
    extras — dashboards and `jq`-based analysis had nothing to filter on.

    A logged exception keeps its traceback and types but, unless
    ``exception_text`` is set (APP_DEBUG), not its text — see
    :func:`_exception_without_text`.
    """

    def __init__(self, *, exception_text: bool = False) -> None:
        super().__init__()
        self.exception_text = exception_text

    def formatException(self, ei) -> str:
        if self.exception_text:
            return super().formatException(ei)
        return _exception_without_text(ei[1])

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


class _UvicornExceptionWithoutText(logging.Filter):
    """An exception that escapes the app past the 500 handler is logged
    again by uvicorn ("Exception in ASGI application"), with uvicorn's own
    formatter. Fold the text-free traceback into the message instead, so that
    line keeps uvicorn's format and leaves out the exception's text."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info and record.exc_info[1] is not None:
            record.msg = f"{record.getMessage()}\n{_exception_without_text(record.exc_info[1])}"
            record.args = None
            record.exc_info = None
            record.exc_text = None
        return True


_UVICORN_EXCEPTION_WITHOUT_TEXT = _UvicornExceptionWithoutText()


def configure_logging(debug: bool = False) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter(exception_text=debug))
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        handlers=[handler],
        force=True,
    )
    uvicorn_error = logging.getLogger("uvicorn.error")
    if debug:
        uvicorn_error.removeFilter(_UVICORN_EXCEPTION_WITHOUT_TEXT)
    else:
        uvicorn_error.addFilter(_UVICORN_EXCEPTION_WITHOUT_TEXT)
    # These loggers quote the uploaded document: WeasyPrint the URLs it
    # refuses to fetch, fontTools the fonts it subsets, pypdf raw bytes of a
    # malformed object, and library warnings (routed to "py.warnings") sheet
    # titles and the like. Real failures reach the converter as exceptions.
    # APP_DEBUG lets them through.
    logging.captureWarnings(True)
    for name in ("weasyprint", "fontTools", "pypdf", "py.warnings"):
        logging.getLogger(name).setLevel(logging.NOTSET if debug else logging.CRITICAL)
    # addFilter skips an instance that is already attached, so the second
    # call at startup does not stack it.
    logging.getLogger("uvicorn.access").addFilter(_ACCESS_LOG_PATH_ONLY)
