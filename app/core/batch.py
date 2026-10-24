# SPDX-License-Identifier: AGPL-3.0-or-later
"""Multi-file batch processing helper — builds ZIP with manifest."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Literal


class BatchFileError(Exception):
    """A per-file batch rejection written for the client (e.g. size, magic bytes).

    Batch routes report ``str(exc)`` for it; any other exception is logged and
    reported generically, since library errors carry internals (CWE-209).
    """


@dataclass
class BatchFileResult:
    """Per-file outcome of a batch operation."""

    name: str
    status: Literal["ok", "error"]
    size_in: int
    size_out: int = 0
    content: bytes | None = None
    error_message: str = ""
    # ``X-FileMorph-Warnings`` tokens for an output the user should know
    # about, e.g. ``resized=2400x1600`` (see compress.py::target_notes).
    notes: list[str] = field(default_factory=list)


def build_batch_zip(
    results: list[BatchFileResult],
    operation: str,
    duration_ms: int,
) -> tuple[bytes, dict]:
    """Build a ZIP of successful outputs; return (zip_bytes, summary).

    A ``manifest.json`` is only included when at least one file failed or
    carries notes — then it explains which file broke and why, or which one
    was scaled down to fit its target size, the only cases where the
    manifest adds value for a normal user. For other batches (the common
    Web-UI path) the ZIP contains just the converted files, keeping the
    download clean. The summary dict is always returned to the caller for
    logging.

    Duplicate output names are disambiguated by numeric suffix so ZIP
    entries remain unique: ``a.png``, ``a_1.png``, ``a_2.png``. A name
    already in the ZIP — ``manifest.json`` or any earlier entry,
    suffixed or not — is never reused; the next free suffix is taken
    instead. Failed files do not take a name.
    """
    succeeded = sum(1 for r in results if r.status == "ok")
    failed = len(results) - succeeded
    total_bytes_in = sum(r.size_in for r in results)
    total_bytes_out = sum(r.size_out for r in results if r.status == "ok")

    summary = {
        "operation": operation,
        "total": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "total_bytes_in": total_bytes_in,
        "total_bytes_out": total_bytes_out,
        "duration_ms": duration_ms,
    }

    buf = io.BytesIO()
    # Name of every entry written so far -> last suffix tried for inputs of that name.
    used: dict[str, int] = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if failed > 0 or any(r.notes for r in results):
            manifest = {
                "summary": summary,
                "files": [
                    {
                        "name": r.name,
                        "status": r.status,
                        "size_in": r.size_in,
                        "size_out": r.size_out if r.status == "ok" else 0,
                        "error_message": r.error_message if r.status == "error" else "",
                        "notes": r.notes,
                    }
                    for r in results
                ],
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
            used["manifest.json"] = 0
        for r in results:
            if r.status != "ok" or r.content is None:
                continue
            name = r.name
            stem, dot, ext = name.rpartition(".")
            while name in used:
                used[r.name] += 1
                suffix = f"_{used[r.name]}"
                name = f"{stem}{suffix}{dot}{ext}" if dot else f"{r.name}{suffix}"
            used[name] = 0
            zf.writestr(name, r.content)

    return buf.getvalue(), summary


def batch_error_response(results: list[BatchFileResult], summary: dict) -> dict:
    """Body for HTTP 422 when every file in the batch failed."""
    return {
        "summary": summary,
        "files": [
            {
                "name": r.name,
                "status": r.status,
                "size_in": r.size_in,
                "error_message": r.error_message,
                "notes": r.notes,
            }
            for r in results
        ],
    }


# P2-1 — header-based batch summary lets the UI render per-file
# results immediately, without unzipping the response body. The
# manifest.json inside the ZIP remains the structured source of
# truth for callers who want full detail; this surface is for the
# common interactive flow.
# Conservative 4 KB across proxies, shared by the Failures and Notes lists.
_LIST_HEADERS_MAX_BYTES = 4 * 1024


def _quote_field(value: str) -> str:
    """URL-encode a free-form field for safe HTTP-header transport.

    Header values are byte strings; non-ASCII content + reserved
    delimiters (``;`` for entries, ``|`` for the name/reason field
    separator) need to be percent-escaped so a downstream proxy or
    the browser's header parser doesn't choke.
    """
    from urllib.parse import quote

    return quote(value, safe="")


def _pair_list(pairs: list[tuple[str, str]], max_bytes: int) -> str:
    """``<name>|<value>;…`` with both fields URL-encoded, capped at
    ``max_bytes`` with a trailing ``...`` sentinel."""
    entries: list[str] = []
    running_bytes = 0
    truncated = False
    for name, value in pairs:
        entry = f"{_quote_field(name)}|{_quote_field(value)}"
        # +1 for the join separator if this isn't the first entry.
        cost = len(entry.encode("ascii")) + (1 if entries else 0)
        if running_bytes + cost > max_bytes:
            truncated = True
            break
        entries.append(entry)
        running_bytes += cost
    if truncated:
        entries.append("...")
    return ";".join(entries)


def batch_summary_headers(results: list[BatchFileResult], summary: dict) -> dict[str, str]:
    """Return the ``X-FileMorph-Batch-*`` response-header set.

    Always emits the three count headers. ``Failures`` lists the
    failed files in ``<name>|<reason>;<name>|<reason>...`` form,
    URL-encoded so a name with spaces or non-ASCII characters
    transports safely. ``Notes`` lists the files with notes the same
    way, the value being the comma-joined tokens (``resized=2400x1600``).
    The two lists share ``_LIST_HEADERS_MAX_BYTES``, the failures first;
    a list that would exceed what is left (large batches) is truncated,
    and a ``…`` sentinel signals the
    UI to point at the manifest.json inside the ZIP for the full
    breakdown. The summary counts in the other three headers always
    reflect the true totals — never the truncated set.
    """
    headers = {
        "X-FileMorph-Batch-Total": str(summary.get("total", len(results))),
        "X-FileMorph-Batch-Succeeded": str(summary.get("succeeded", 0)),
        "X-FileMorph-Batch-Failed": str(summary.get("failed", 0)),
    }
    budget = _LIST_HEADERS_MAX_BYTES
    failures = [(r.name, r.error_message or "unknown") for r in results if r.status == "error"]
    if failures:
        headers["X-FileMorph-Batch-Failures"] = _pair_list(failures, budget)
        budget -= len(headers["X-FileMorph-Batch-Failures"])
    notes = [(r.name, ",".join(r.notes)) for r in results if r.status == "ok" and r.notes]
    if notes:
        headers["X-FileMorph-Batch-Notes"] = _pair_list(notes, budget)
    return headers
