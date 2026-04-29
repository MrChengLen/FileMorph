"""Security regression tests — covers A-1, A-3, A-4, A-5, A-7 and v1.0.2 fixes."""

import re


# ---------------------------------------------------------------------------
# Security headers (A-4)
# ---------------------------------------------------------------------------


def test_security_headers_present(client):
    """All OWASP baseline security headers must be present on every response."""
    res = client.get("/")
    assert res.headers.get("x-content-type-options") == "nosniff"
    assert res.headers.get("x-frame-options") == "DENY"
    assert "strict-origin-when-cross-origin" in res.headers.get("referrer-policy", "")
    assert "default-src" in res.headers.get("content-security-policy", "")


def test_security_headers_on_api_responses(client):
    """Security headers must also appear on API JSON responses."""
    res = client.get("/api/v1/health")
    assert res.headers.get("x-content-type-options") == "nosniff"
    assert res.headers.get("x-frame-options") == "DENY"


# ---------------------------------------------------------------------------
# Custom error handlers (A-5)
# ---------------------------------------------------------------------------


def test_404_returns_html_for_browser(client):
    """Unknown UI paths return 404 HTML, not a raw JSON error."""
    res = client.get("/this-path-does-not-exist")
    assert res.status_code == 404
    assert "text/html" in res.headers.get("content-type", "")


def test_404_returns_json_for_api(client):
    """Unknown /api/ paths return structured JSON 404."""
    res = client.get("/api/v1/nonexistent-endpoint")
    assert res.status_code == 404
    assert res.json()["detail"] == "Endpoint not found."


# ---------------------------------------------------------------------------
# Path traversal (A-1)
# ---------------------------------------------------------------------------


def test_path_traversal_filename_sanitized(client, auth_headers, tmp_path):
    """A filename containing ../ must not appear as a path in the response."""
    from PIL import Image

    img = Image.new("RGB", (10, 10), color=(255, 0, 0))
    path = tmp_path / "test.jpg"
    img.save(str(path))

    with path.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("../../etc/passwd.jpg", f, "image/jpeg")},
            data={"target_format": "png"},
        )
    # Should succeed (file is a valid JPEG)
    assert res.status_code == 200
    # Content-Disposition must NOT contain the path traversal sequence
    disposition = res.headers.get("content-disposition", "")
    assert ".." not in disposition
    assert "etc/passwd" not in disposition


# ---------------------------------------------------------------------------
# Magic-byte validation (A-1 extension)
# ---------------------------------------------------------------------------


def test_magic_byte_pe_blocked(client, auth_headers, tmp_path):
    """A Windows PE binary disguised as a JPEG must be rejected (400)."""
    path = tmp_path / "evil.jpg"
    path.write_bytes(b"MZ\x90\x00" + b"\x00" * 200)
    with path.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("evil.jpg", f, "image/jpeg")},
            data={"target_format": "png"},
        )
    assert res.status_code == 400
    assert "not permitted" in res.json()["detail"].lower()


def test_magic_byte_elf_blocked(client, auth_headers, tmp_path):
    """A Linux ELF binary disguised as a JPEG must be rejected."""
    path = tmp_path / "evil.jpg"
    path.write_bytes(b"\x7fELF" + b"\x00" * 200)
    with path.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("evil.jpg", f, "image/jpeg")},
            data={"target_format": "png"},
        )
    assert res.status_code == 400


def test_magic_byte_shell_blocked(client, auth_headers, tmp_path):
    """A shell script disguised as an image must be rejected."""
    path = tmp_path / "evil.jpg"
    path.write_bytes(b"#!/bin/bash\nrm -rf /\n" + b"\x00" * 100)
    with path.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("evil.jpg", f, "image/jpeg")},
            data={"target_format": "png"},
        )
    assert res.status_code == 400


def test_valid_jpeg_not_blocked(client, auth_headers, sample_jpg):
    """A valid JPEG must pass magic-byte check and convert successfully."""
    with sample_jpg.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("valid.jpg", f, "image/jpeg")},
            data={"target_format": "png"},
        )
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# Exception detail not leaked (A-3)
# ---------------------------------------------------------------------------


def test_exception_detail_not_leaked_on_corrupt_file(client, auth_headers, tmp_path):
    """A corrupt file must return a generic error, not Python internals."""
    path = tmp_path / "corrupt.jpg"
    # Valid JPEG SOI marker but then garbage — triggers Pillow error
    path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
    with path.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("corrupt.jpg", f, "image/jpeg")},
            data={"target_format": "png"},
        )
    assert res.status_code in (400, 422, 500)
    body = res.json().get("detail", "")
    # Must NOT leak internals
    assert "Traceback" not in body
    assert "/tmp/" not in body
    assert "PIL" not in body
    assert "OSError" not in body


# ---------------------------------------------------------------------------
# Content-Disposition: original filename, not UUID (A-7 + GDPR)
# ---------------------------------------------------------------------------


def test_download_filename_reflects_original_name(client, auth_headers, sample_jpg):
    """The Content-Disposition filename must use the original upload name, not a UUID."""
    with sample_jpg.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("my_document.jpg", f, "image/jpeg")},
            data={"target_format": "png"},
        )
    assert res.status_code == 200
    disposition = res.headers.get("content-disposition", "")
    assert "my_document" in disposition
    # UUID hex (32 lowercase hex chars) must NOT appear in the download name
    assert not re.search(r"[0-9a-f]{32}", disposition)


def test_download_filename_extension_matches_target(client, auth_headers, sample_jpg):
    """The download file extension must match the requested target format."""
    with sample_jpg.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("photo.jpg", f, "image/jpeg")},
            data={"target_format": "webp"},
        )
    assert res.status_code == 200
    disposition = res.headers.get("content-disposition", "")
    assert ".webp" in disposition


# ---------------------------------------------------------------------------
# CORS: default restricts credentials
# ---------------------------------------------------------------------------


def test_cors_no_wildcard_credentials(client):
    """Default CORS must not allow credentials with wildcard origin."""
    res = client.options(
        "/api/v1/convert",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "POST"},
    )
    # Either no allow-origin header, or it must not be a wildcard
    acao = res.headers.get("access-control-allow-origin", "")
    acac = res.headers.get("access-control-allow-credentials", "false")
    # Must not combine wildcard with credentials
    assert not (acao == "*" and acac.lower() == "true")
