# SPDX-License-Identifier: AGPL-3.0-or-later
"""An empty file input in a plain browser form arrives as a part with
``filename=""`` and no content. Since FastAPI 0.150 such a part counts as
missing, so the upload routes answer with the generic 422 for a missing field
instead of their own message about the file name. FileMorph's pages only send
files the user picked, so this concerns other clients. The test pins the
answer, so a framework update that changes it again shows up here."""

import pytest

_EMPTY_FILE_PART = (
    '--b\r\nContent-Disposition: form-data; name="{field}"; filename=""\r\n'
    "Content-Type: application/octet-stream\r\n\r\n\r\n"
)


def _field(name: str, value: str) -> str:
    return f'--b\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'


def _file(name: str) -> str:
    return (
        f'--b\r\nContent-Disposition: form-data; name="{name}"; filename="a.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n%PDF-\r\n"
    )


@pytest.mark.parametrize(
    ("path", "field", "extra"),
    [
        ("/api/v1/convert", "file", _field("target_format", "jpg")),
        ("/api/v1/compress", "file", ""),
        ("/api/v1/convert/batch", "files", _field("target_formats", "jpg")),
        ("/api/v1/compress/batch", "files", ""),
        ("/api/v1/pdf/extract", "file", _field("pages", "1")),
        ("/api/v1/pdf/split", "file", ""),
        ("/api/v1/pdf/compress", "file", _field("target_kb", "100")),
        ("/api/v1/pdf/insert", "file", _file("insert_file")),
        ("/api/v1/pdf/insert", "insert_file", _file("file")),
        ("/api/v1/ai/redact/detect", "file", ""),
        ("/api/v1/ai/redact/apply", "file", ""),
    ],
    ids=[
        "convert",
        "compress",
        "convert-batch",
        "compress-batch",
        "pdf-extract",
        "pdf-split",
        "pdf-compress",
        "pdf-insert",
        "pdf-insert-second-file",
        "ai-redact-detect",
        "ai-redact-apply",
    ],
)
def test_empty_browser_file_part_counts_as_missing(client, auth_headers, path, field, extra):
    body = _EMPTY_FILE_PART.format(field=field) + extra + "--b--\r\n"
    res = client.post(
        path,
        headers={**auth_headers, "Content-Type": "multipart/form-data; boundary=b"},
        content=body.encode(),
    )
    assert res.status_code == 422
    errors = res.json()["errors"]
    assert [(e["type"], e["loc"]) for e in errors] == [("missing", ["body", field])]
