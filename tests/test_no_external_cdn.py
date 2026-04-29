# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guard the self-hosted-Tailwind invariant.

The Web UI used to load `cdn.tailwindcss.com`, which broke a strict CSP
and put a third-party request on every page. These tests catch any
silent re-introduction — either in the HTML templates or in the CSP
allow-list — and also verify that a hashed `tailwind.<sha>.css` bundle
is shipped so the swap actually works at runtime with a far-future,
`immutable` Cache-Control."""

import re
from pathlib import Path


_CDN_HOST = "cdn.tailwindcss.com"
_HASHED = re.compile(r"^tailwind\.[a-f0-9]{6,}\.css$")


def _committed_tailwind_bundle() -> Path:
    """Return the committed hashed Tailwind bundle or raise AssertionError.

    Scanning the directory beats hard-coding the hash — the hash rotates
    every rebuild and the test must survive those rotations."""
    css_dir = Path("app/static/css")
    candidates = [p for p in css_dir.glob("tailwind.*.css") if _HASHED.match(p.name)]
    assert candidates, (
        "No hashed tailwind.*.css found under app/static/css/ — "
        "run `bash scripts/build-tailwind.sh`."
    )
    assert len(candidates) == 1, (
        f"Multiple hashed bundles present ({[c.name for c in candidates]}); "
        "the build script should purge stale ones."
    )
    return candidates[0]


def test_base_template_has_no_cdn_script(client):
    """The rendered index page must not reference the Tailwind CDN
    anywhere — no <script src="…">, no preconnect, no fallback link."""
    r = client.get("/")
    assert r.status_code == 200
    assert _CDN_HOST not in r.text, (
        f"Tailwind CDN host '{_CDN_HOST}' found in rendered HTML; "
        "the template should link the self-hosted hashed bundle instead."
    )


def test_csp_header_does_not_allow_tailwind_cdn(client):
    """CSP must not allowlist the CDN. If someone re-adds it to the
    policy, future CDN-loaded scripts would silently execute again."""
    r = client.get("/")
    csp = r.headers.get("content-security-policy", "")
    assert csp, "CSP header missing from HTML response"
    assert _CDN_HOST not in csp, (
        f"'{_CDN_HOST}' still appears in CSP:\n  {csp}\nDrop it now that we self-host Tailwind."
    )


def test_tailwind_bundle_is_shipped_and_nonempty():
    """A hashed tailwind.<sha>.css bundle must be committed. An empty /
    missing file means the build step was skipped and the whole UI would
    render unstyled in production."""
    bundle = _committed_tailwind_bundle()
    # 1 KB floor is an arbitrary sanity bar; the real build is ~17 KB.
    # Anything near zero means Tailwind produced nothing (bad config or
    # empty content globs).
    assert bundle.stat().st_size > 1024, (
        f"{bundle.name} is suspiciously small ({bundle.stat().st_size} B)."
    )


def test_tailwind_bundle_served_with_immutable_cache(client):
    """The hashed bundle must be served with a far-future `immutable`
    Cache-Control — that's the whole point of content-hashing the
    filename. A plain 5-minute `must-revalidate` here means the regex
    in CachingStaticFiles stopped matching the new filename shape."""
    bundle = _committed_tailwind_bundle()
    r = client.get(f"/static/css/{bundle.name}")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("text/css")
    cache_control = r.headers.get("cache-control", "")
    assert "immutable" in cache_control, (
        f"Expected `immutable` Cache-Control for hashed bundle, got: {cache_control!r}"
    )
    assert "max-age=31536000" in cache_control, (
        f"Expected 1-year max-age for hashed bundle, got: {cache_control!r}"
    )


def test_base_template_links_the_hashed_bundle(client):
    """Rendered HTML must point at the current hashed filename — not
    the legacy `/static/css/tailwind.css`. A mismatch here means the
    Jinja global is stale or `tailwind_css_filename()` fell back."""
    bundle = _committed_tailwind_bundle()
    r = client.get("/")
    assert r.status_code == 200
    assert f"/static/css/{bundle.name}" in r.text, (
        f"index page is not linking the committed hashed bundle {bundle.name}"
    )
