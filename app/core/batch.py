# SPDX-License-Identifier: AGPL-3.0-or-later
"""Multi-file batch processing helper — builds ZIP with manifest."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from typing import Literal


@dataclass
class BatchFileResult:
    """Per-file outcome of a batch operation."""

    name: str
    status: Literal["ok", "error"]
    size_in: int
    size_out: int = 0
    content: bytes | None = None
    error_message: str = ""


def build_batch_zip(
    results: list[BatchFileResult],
    operation: str,
    duration_ms: int,
) -> tuple[bytes, dict]:
    """Build a ZIP of successful outputs; return (zip_bytes, summary).

    A ``manifest.json`` is only included when at least one file failed —
    then it explains which file broke and why, which is the only case
    where the manifest adds value for a normal user. For all-success
    batches (the common Web-UI path) the ZIP contains just the converted
    files, keeping the download clean. The summary dict is always
    returned to the caller for logging.

    Duplicate output names are disambiguated by numeric suffix so ZIP
    entries remain unique.
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
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if failed > 0:
            manifest = {
                "summary": summary,
                "files": [
                    {
                        "name": r.name,
                        "status": r.status,
                        "size_in": r.size_in,
                        "size_out": r.size_out if r.status == "ok" else 0,
                        "error_message": r.error_message if r.status == "error" else "",
                    }
                    for r in results
                ],
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        used: dict[str, int] = {}
        for r in results:
            if r.status != "ok" or r.content is None:
                continue
            name = r.name
            if name in used:
                used[name] += 1
                stem, dot, ext = name.rpartition(".")
                suffix = f"_{used[name]}"
                name = f"{stem}{suffix}{dot}{ext}" if dot else f"{name}{suffix}"
            else:
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
            }
            for r in results
        ],
    }
