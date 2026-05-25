# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tier quota enforcement — file size limits."""

import io


def test_anonymous_upload_over_30mb_rejected(client, auth_headers):
    """Anonymous (no JWT, no user) uploads over 30 MB must return 413."""
    # Build a ~31 MB JPEG-headed payload (valid magic bytes so we don't hit magic-byte block first).
    big = b"\xff\xd8\xff\xe0" + b"\x00" * (31 * 1024 * 1024)
    res = client.post(
        "/api/v1/convert",
        files={"file": ("big.jpg", io.BytesIO(big), "image/jpeg")},
        data={"target_format": "png"},
        headers=auth_headers,
    )
    assert res.status_code == 413
    body = res.json()
    assert "30 MB" in body["detail"]
    assert "anonymous" in body["detail"].lower()
    # PR-uxfix-413: structured error code distinguishes "your upload was
    # too big" (input gate) from "the rendered output is over cap"
    # (after conversion). Both 413; the UI branches on the header.
    assert res.headers.get("X-FileMorph-Error-Code") == "input_too_large"


def test_anonymous_upload_under_20mb_not_size_rejected(client, auth_headers, sample_jpg):
    """A small file from anonymous must NOT be rejected for size reasons."""
    with sample_jpg.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            files={"file": ("sample.jpg", f, "image/jpeg")},
            data={"target_format": "png"},
            headers=auth_headers,
        )
    # Small file: either succeeds (200) or fails for other reasons, but NOT 413.
    assert res.status_code != 413


def test_anonymous_compress_over_30mb_rejected(client, auth_headers):
    """Compression endpoint must enforce the same 30 MB anonymous limit."""
    big = b"\xff\xd8\xff\xe0" + b"\x00" * (31 * 1024 * 1024)
    res = client.post(
        "/api/v1/compress",
        files={"file": ("big.jpg", io.BytesIO(big), "image/jpeg")},
        data={"quality": 80},
        headers=auth_headers,
    )
    assert res.status_code == 413
    assert "30 MB" in res.json()["detail"]
    assert res.headers.get("X-FileMorph-Error-Code") == "input_too_large"
