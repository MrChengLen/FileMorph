#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SEO foundation audit for a running FileMorph instance.

Checks the technical SEO basics that every public-facing deployment needs
before search engines can rank it: robots.txt, sitemap.xml, canonical URL,
meta description, viewport, OpenGraph image, Twitter Card, JSON-LD
structured data.

This script does NOT fix anything — it lists the gaps. Implementations of
the missing pieces happen in dedicated SEO sprints.

Usage:
    # Audit local dev server
    python scripts/audit_seo_basics.py

    # Audit production
    python scripts/audit_seo_basics.py --base-url https://filemorph.io

    # Skip OG-image dimension fetch (saves a HEAD request)
    python scripts/audit_seo_basics.py --skip-og-image

Exit code: 0 if all critical checks pass, 1 if any 🔴 / 🟡 remain.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urljoin

import requests

# Force UTF-8 output on Windows so emoji status indicators render.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


@dataclass
class CheckResult:
    name: str
    status: str  # "pass" | "warn" | "fail"
    detail: str

    @property
    def symbol(self) -> str:
        return {"pass": "✅", "warn": "🟡", "fail": "🔴"}[self.status]


# ── Endpoint checks ────────────────────────────────────────────────────────────


def check_robots_txt(base_url: str, session: requests.Session) -> CheckResult:
    url = urljoin(base_url + "/", "robots.txt")
    try:
        r = session.get(url, timeout=10)
    except requests.RequestException as exc:
        return CheckResult("robots.txt", "fail", f"request failed: {exc}")

    if r.status_code == 404:
        return CheckResult("robots.txt", "fail", "404 — endpoint not implemented (S6-SEO sprint)")
    if r.status_code != 200:
        return CheckResult("robots.txt", "fail", f"status {r.status_code}")

    body = r.text
    if "sitemap:" not in body.lower():
        return CheckResult(
            "robots.txt",
            "warn",
            "200 OK but no `Sitemap:` directive — search engines won't auto-discover sitemap",
        )
    if "user-agent:" not in body.lower():
        return CheckResult("robots.txt", "warn", "200 OK but no `User-agent:` directive")
    return CheckResult("robots.txt", "pass", f"200 OK, {len(body)} bytes, has Sitemap directive")


def check_sitemap_xml(base_url: str, session: requests.Session) -> CheckResult:
    url = urljoin(base_url + "/", "sitemap.xml")
    try:
        r = session.get(url, timeout=10)
    except requests.RequestException as exc:
        return CheckResult("sitemap.xml", "fail", f"request failed: {exc}")

    if r.status_code == 404:
        return CheckResult("sitemap.xml", "fail", "404 — endpoint not implemented (S6-SEO sprint)")
    if r.status_code != 200:
        return CheckResult("sitemap.xml", "fail", f"status {r.status_code}")

    try:
        root = ET.fromstring(r.text)
    except ET.ParseError as exc:
        return CheckResult("sitemap.xml", "fail", f"XML parse error: {exc}")

    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = root.findall("sm:url", ns) or root.findall("url")
    if not urls:
        return CheckResult("sitemap.xml", "warn", "valid XML but no <url> entries")
    return CheckResult("sitemap.xml", "pass", f"200 OK, {len(urls)} URL entries")


# ── HTML page checks ───────────────────────────────────────────────────────────


def _fetch_homepage(
    base_url: str, session: requests.Session
) -> tuple[str | None, CheckResult | None]:
    try:
        r = session.get(base_url, timeout=10)
    except requests.RequestException as exc:
        return None, CheckResult("homepage HTML", "fail", f"request failed: {exc}")
    if r.status_code != 200:
        return None, CheckResult("homepage HTML", "fail", f"status {r.status_code}")
    return r.text, None


def check_title(html: str) -> CheckResult:
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    if not m:
        return CheckResult("<title>", "fail", "missing")
    title = m.group(1).strip()
    if len(title) > 60:
        return CheckResult(
            "<title>",
            "warn",
            f"{len(title)} chars - Google truncates after ~60: '{title[:60]}...'",
        )
    if len(title) < 10:
        return CheckResult("<title>", "warn", f"only {len(title)} chars - too short for SEO")
    return CheckResult("<title>", "pass", f"{len(title)} chars: '{title}'")


def check_meta_description(html: str) -> CheckResult:
    m = re.search(
        r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if not m:
        return CheckResult('<meta name="description">', "fail", "missing")
    desc = m.group(1).strip()
    if len(desc) > 160:
        return CheckResult(
            '<meta name="description">', "warn", f"{len(desc)} chars — Google truncates after ~155"
        )
    if len(desc) < 50:
        return CheckResult(
            '<meta name="description">', "warn", f"only {len(desc)} chars — too short"
        )
    return CheckResult('<meta name="description">', "pass", f"{len(desc)} chars")


def check_canonical(html: str, base_url: str) -> CheckResult:
    m = re.search(
        r'<link\s+rel=["\']canonical["\']\s+href=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if not m:
        return CheckResult('<link rel="canonical">', "fail", "missing")
    href = m.group(1).strip()
    if not (href.startswith("http://") or href.startswith("https://")):
        return CheckResult('<link rel="canonical">', "warn", f"relative URL: {href}")
    return CheckResult('<link rel="canonical">', "pass", href)


def check_viewport(html: str) -> CheckResult:
    m = re.search(
        r'<meta\s+name=["\']viewport["\']\s+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if not m:
        return CheckResult('<meta name="viewport">', "fail", "missing — mobile-unfriendly")
    content = m.group(1).strip()
    if "width=device-width" not in content:
        return CheckResult('<meta name="viewport">', "warn", f"unusual: {content}")
    return CheckResult('<meta name="viewport">', "pass", content)


def check_og_tags(html: str) -> list[CheckResult]:
    results: list[CheckResult] = []
    required = ["og:title", "og:description", "og:type", "og:image", "og:url"]
    for prop in required:
        m = re.search(
            rf'<meta\s+property=["\']{re.escape(prop)}["\']\s+content=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE,
        )
        if not m:
            results.append(CheckResult(f'<meta property="{prop}">', "fail", "missing"))
        else:
            val = m.group(1).strip()
            results.append(
                CheckResult(
                    f'<meta property="{prop}">', "pass", val[:80] + ("…" if len(val) > 80 else "")
                )
            )
    return results


def check_twitter_card(html: str) -> CheckResult:
    m = re.search(
        r'<meta\s+name=["\']twitter:card["\']\s+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if not m:
        return CheckResult('<meta name="twitter:card">', "fail", "missing")
    return CheckResult('<meta name="twitter:card">', "pass", m.group(1))


def check_og_image_dimensions(html: str, base_url: str, session: requests.Session) -> CheckResult:
    m = re.search(
        r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if not m:
        return CheckResult("og:image dimensions", "fail", "no og:image meta tag")
    img_url = m.group(1).strip()
    if not img_url.startswith(("http://", "https://")):
        img_url = urljoin(base_url + "/", img_url.lstrip("/"))

    try:
        r = session.get(img_url, timeout=15)
    except requests.RequestException as exc:
        return CheckResult("og:image dimensions", "fail", f"fetch failed: {exc}")
    if r.status_code != 200:
        return CheckResult("og:image dimensions", "fail", f"status {r.status_code}")

    try:
        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(r.content))
        w, h = img.size
    except Exception as exc:
        return CheckResult("og:image dimensions", "warn", f"could not parse image: {exc}")

    size_kb = len(r.content) // 1024
    target_w, target_h = 1200, 630
    if (w, h) == (target_w, target_h):
        return CheckResult("og:image dimensions", "pass", f"{w}x{h}, {size_kb} KB")
    if abs(w / h - target_w / target_h) < 0.05:
        return CheckResult(
            "og:image dimensions",
            "warn",
            f"{w}x{h} (recommended 1200x630, ratio close), {size_kb} KB",
        )
    return CheckResult(
        "og:image dimensions",
        "warn",
        f"{w}x{h} (recommended 1200x630), {size_kb} KB",
    )


def check_jsonld(html: str) -> list[CheckResult]:
    blocks = re.findall(
        r'<script\s+type=["\']application/ld\+json["\'][^>]*>([\s\S]+?)</script>',
        html,
        re.IGNORECASE,
    )
    if not blocks:
        return [
            CheckResult(
                "JSON-LD structured data",
                "fail",
                'no <script type="application/ld+json"> blocks (S6-SEO sprint)',
            )
        ]

    results: list[CheckResult] = []
    types_found: list[str] = []
    for i, block in enumerate(blocks):
        try:
            data = json.loads(block)
        except json.JSONDecodeError as exc:
            results.append(CheckResult(f"JSON-LD block #{i + 1}", "fail", f"parse error: {exc}"))
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            t = item.get("@type", "<unknown>")
            types_found.append(t if isinstance(t, str) else ",".join(t))

    if types_found:
        results.append(
            CheckResult("JSON-LD structured data", "pass", f"@types: {', '.join(types_found)}")
        )

    expected = {"WebApplication", "SoftwareApplication"}
    missing = expected - set(types_found)
    if missing:
        results.append(
            CheckResult(
                "JSON-LD coverage",
                "warn",
                f"missing recommended @types: {', '.join(sorted(missing))}",
            )
        )
    return results


# ── Driver ─────────────────────────────────────────────────────────────────────


def run_audit(base_url: str, skip_og_image: bool) -> list[CheckResult]:
    session = requests.Session()
    session.headers["User-Agent"] = "FileMorph-SEO-Audit/1.0"
    results: list[CheckResult] = []

    results.append(check_robots_txt(base_url, session))
    results.append(check_sitemap_xml(base_url, session))

    html, err = _fetch_homepage(base_url, session)
    if err:
        results.append(err)
        return results

    results.append(check_title(html))
    results.append(check_meta_description(html))
    results.append(check_canonical(html, base_url))
    results.append(check_viewport(html))
    results.extend(check_og_tags(html))
    results.append(check_twitter_card(html))
    if not skip_og_image:
        results.append(check_og_image_dimensions(html, base_url, session))
    results.extend(check_jsonld(html))

    return results


def print_results(results: list[CheckResult], base_url: str) -> int:
    print(f"\nSEO Foundation Audit — {base_url}\n")
    by_status = {"pass": 0, "warn": 0, "fail": 0}
    for r in results:
        by_status[r.status] += 1
        print(f"  {r.symbol}  {r.name:<35}  {r.detail}")

    total = len(results)
    print(
        f"\nSummary: {by_status['pass']} pass / {by_status['warn']} warn / "
        f"{by_status['fail']} fail   (total {total})"
    )
    return 0 if by_status["fail"] == 0 and by_status["warn"] == 0 else 1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default="http://localhost:8000", help="Origin to audit")
    p.add_argument(
        "--skip-og-image", action="store_true", help="Skip OG-image fetch + dimension check"
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    results = run_audit(args.base_url.rstrip("/"), args.skip_og_image)
    return print_results(results, args.base_url)


if __name__ == "__main__":
    sys.exit(main())
