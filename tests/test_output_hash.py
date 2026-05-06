# SPDX-License-Identifier: AGPL-3.0-or-later
"""NEU-B.2: ``X-Output-SHA256`` header on convert + compress.

The header is the integrity anchor that lets a downstream auditor
(GoBD-archival, beA-Anhang-Trail, eDiscovery) recompute the file's
hash from disk and compare it to what FileMorph attested at the
moment of conversion. This test suite locks the contract:

1. The header is present on the success response.
2. It is lower-case hex, exactly 64 chars (SHA-256 output).
3. It matches a recomputed SHA-256 of the response body — i.e. the
   server is hashing what it actually returns to the client, not
   some intermediate buffer.

If any of these three break, the audit-log payload (which carries
the same hash) and the client-visible attestation diverge — that is
exactly the kind of silent drift the chain is meant to prevent.
"""

from __future__ import annotations

import hashlib
import io


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_convert_response_carries_output_sha256_header(client, auth_headers, sample_jpg):
    """JPG → PNG conversion exposes a verifiable SHA-256 of the output."""
    with sample_jpg.open("rb") as f:
        resp = client.post(
            "/api/v1/convert",
            files={"file": ("sample.jpg", f, "image/jpeg")},
            data={"target_format": "png"},
            headers=auth_headers,
        )
    assert resp.status_code == 200, resp.text
    header_hash = resp.headers.get("X-Output-SHA256")
    assert header_hash is not None, "missing X-Output-SHA256 on /convert success"
    assert len(header_hash) == 64
    assert header_hash == header_hash.lower()
    assert all(c in "0123456789abcdef" for c in header_hash)
    # The header must hash the body the client actually receives.
    assert header_hash == _sha256(resp.content)


def test_compress_response_carries_output_sha256_header(client, auth_headers, sample_jpg):
    """JPEG compression exposes a verifiable SHA-256 of the output."""
    with sample_jpg.open("rb") as f:
        resp = client.post(
            "/api/v1/compress",
            files={"file": ("sample.jpg", f, "image/jpeg")},
            data={"quality": "60"},
            headers=auth_headers,
        )
    assert resp.status_code == 200, resp.text
    header_hash = resp.headers.get("X-Output-SHA256")
    assert header_hash is not None, "missing X-Output-SHA256 on /compress success"
    assert len(header_hash) == 64
    assert header_hash == header_hash.lower()
    assert header_hash == _sha256(resp.content)


def test_compress_target_size_keeps_output_hash_and_target_headers(
    client, auth_headers, sample_jpg
):
    """The target-size path adds ``X-FileMorph-Achieved-Bytes`` /
    ``X-FileMorph-Final-Quality`` next to the integrity hash; both
    surfaces must coexist on the same response."""
    with sample_jpg.open("rb") as f:
        resp = client.post(
            "/api/v1/compress",
            files={"file": ("sample.jpg", f, "image/jpeg")},
            data={"target_size_kb": "5"},
            headers=auth_headers,
        )
    assert resp.status_code == 200, resp.text
    assert "X-Output-SHA256" in resp.headers
    assert "X-FileMorph-Achieved-Bytes" in resp.headers
    assert "X-FileMorph-Final-Quality" in resp.headers
    assert resp.headers["X-Output-SHA256"] == _sha256(resp.content)


def test_output_sha256_differs_for_different_inputs(client, auth_headers, tmp_path):
    """Two different JPEGs must produce two different output hashes —
    catches any regression where the helper accidentally caches the
    last hash, returns a constant, or hashes the input rather than
    the output."""
    from PIL import Image

    img1 = Image.new("RGB", (40, 40), color=(255, 0, 0))
    img2 = Image.new("RGB", (40, 40), color=(0, 255, 0))
    p1 = tmp_path / "red.jpg"
    p2 = tmp_path / "green.jpg"
    img1.save(p1, format="JPEG", quality=90)
    img2.save(p2, format="JPEG", quality=90)

    def _convert(path):
        with path.open("rb") as f:
            r = client.post(
                "/api/v1/convert",
                files={"file": (path.name, f, "image/jpeg")},
                data={"target_format": "png"},
                headers=auth_headers,
            )
        assert r.status_code == 200, r.text
        return r.headers["X-Output-SHA256"]

    assert _convert(p1) != _convert(p2)


def test_helper_matches_streaming_definition(tmp_path):
    """Direct helper-level check: ``_sha256_file`` produces the same
    digest whether the input is one chunk or many. Guards against any
    refactor that changes the chunked-read semantics."""
    from app.api.routes.convert import _sha256_file

    payload = b"FileMorph integrity-anchor reference vector\n" * 10_000
    path = tmp_path / "blob.bin"
    path.write_bytes(payload)

    expected = hashlib.sha256(payload).hexdigest()
    assert _sha256_file(path) == expected
    # Tiny chunk size should not change the digest.
    assert _sha256_file(path, chunk_size=17) == expected
    # And the standalone sha256 of an in-memory buffer agrees.
    assert hashlib.sha256(io.BytesIO(payload).read()).hexdigest() == expected
