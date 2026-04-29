# SPDX-License-Identifier: AGPL-3.0-or-later
"""S1-D sanity guards for the batch-upload UI.

The API has carried `/convert/batch` + `/compress/batch` for some time and
pricing copy advertises batch uploads — but until this sprint the Web UI
only ever posted a single file. These cheap regression tests catch a
silent revert (accidentally dropping `multiple`, or the JS losing its
batch branch) without needing a full browser harness."""

from pathlib import Path


def test_index_file_input_supports_multiple(client):
    """The file <input> must carry `multiple`; without it the browser
    picker only ever returns one file, regardless of JS wiring."""
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert 'id="file-input"' in body
    # `multiple` sits on the same <input> line as `id="file-input"` in the
    # current template; assert on the input tag's attribute presence rather
    # than a loose `'multiple' in body` which would pass on any stray match.
    input_line = next(
        (line for line in body.splitlines() if 'id="file-input"' in line),
        "",
    )
    assert "multiple" in input_line, "file-input lost its `multiple` attribute"


def test_app_js_routes_to_batch_endpoints():
    """The JS must know both batch endpoint prefixes and must branch on
    `isBatch`; losing any of these would silently disable batch uploads
    in the web UI while the API continues to advertise them."""
    js = Path("app/static/js/app.js").read_text(encoding="utf-8")
    assert "/api/v1/convert" in js
    assert "/api/v1/compress" in js
    # `${base}/batch` is the template-literal that composes the batch URL;
    # its loss is the most likely silent regression.
    assert "${base}/batch" in js
    assert "isBatch" in js


def test_body_has_api_base_data_attribute(client):
    """`<body data-api-base=…>` is how the JS learns whether uploads should
    go cross-origin to a tunnel subdomain. Empty-string default keeps dev
    + tests same-origin; losing the attribute would orphan the wiring."""
    r = client.get("/")
    assert r.status_code == 200
    body_line = next(
        (line for line in r.text.splitlines() if line.lstrip().startswith("<body")),
        "",
    )
    assert "data-api-base=" in body_line, "<body> lost its data-api-base attribute"


def test_app_js_prefixes_upload_endpoint_with_upload_base():
    """Upload POSTs must go through `UPLOAD_BASE + …` so a deployment
    can route heavy uploads to a separate subdomain. Format + auth
    fetches stay same-origin by design."""
    js = Path("app/static/js/app.js").read_text(encoding="utf-8")
    assert "UPLOAD_BASE" in js, "UPLOAD_BASE constant missing from app.js"
    assert "document.body" in js and "dataset.apiBase" in js, (
        "UPLOAD_BASE is no longer sourced from <body data-api-base>"
    )
    # The upload endpoint is the only one prefixed; the format-list GET
    # stays a plain `/api/v1/formats` string.
    assert "UPLOAD_BASE + (isBatch" in js, (
        "upload endpoint no longer composed as UPLOAD_BASE + base"
    )


def test_cors_exposes_content_disposition_for_download_filename():
    """Browsers hide non-simple response headers from cross-origin JS
    unless the server lists them in `Access-Control-Expose-Headers`.
    `Content-Disposition` is the one the Web UI reads to derive the
    download filename — without exposure, the client falls back to a
    bare "result" and the saved file has no extension.

    Direct regression guard on the class of bug introduced by the S1.5
    cross-origin split: shipping a new network boundary without auditing
    every adjacent CORS hardening surface. Introspects middleware config
    directly so this is deterministic regardless of test-client origin
    or runtime settings."""
    from starlette.middleware.cors import CORSMiddleware

    from app.main import app

    cors = next(
        (m for m in app.user_middleware if m.cls is CORSMiddleware),
        None,
    )
    assert cors is not None, "CORSMiddleware no longer registered on the app"
    expose = cors.kwargs.get("expose_headers") or []
    assert "Content-Disposition" in expose, (
        "CORSMiddleware must expose Content-Disposition so the Web UI can "
        "read the server-set download filename on cross-origin uploads. "
        f"Currently expose_headers={expose!r}."
    )


def test_csp_connect_src_extends_to_api_base_when_set():
    """If a deployment ships cross-origin upload POSTs (the S1.5 split),
    the CSP `connect-src` MUST allowlist that origin — browsers refuse
    cross-origin fetches when the policy says `'self'` only.

    This is a direct regression guard on a real production bug: the
    frontend was routed to a separate `api.*` subdomain but the CSP
    still declared `connect-src 'self'`, so the browser blocked every
    upload before it even hit the network. Tested against the pure
    builder because the running app freezes settings at startup."""
    from app.main import _build_csp_header

    # Default (same-origin deployment) keeps the tight policy.
    tight = _build_csp_header("")
    assert "connect-src 'self';" in tight
    assert "connect-src 'self' " not in tight, "extra origin leaked into same-origin CSP"

    # With an API base URL, the origin is added to connect-src.
    split = _build_csp_header("https://api.example.com")
    assert "connect-src 'self' https://api.example.com;" in split, (
        f"API base not present in connect-src: {split!r}"
    )
    # Still tight elsewhere — api base leaks into connect-src only.
    assert "script-src 'self';" in split
    assert "default-src 'self';" in split
