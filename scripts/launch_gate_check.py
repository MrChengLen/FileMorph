#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hard-Launch-Gate readiness check for FileMorph.

Verifies the launch-readiness criteria (run --help for the gates checked)
are green before any public release.

Two modes:
    --local  (default): runs against `http://localhost:8000`. Performs a
             quick perf burst (50 × jpg→webp 100 KB), checks asset files
             on disk, checks env vars. Does NOT cover the 7-day error
             gate — that needs production logs.

    --logs PATH: also parses a production JSON-lines log file at PATH and
             reports actual 7-day error rate + p95. Use this on the live
             host: ``python scripts/launch_gate_check.py --logs /path/to/app.log``

Usage:
    # Local pre-launch self-check
    python scripts/launch_gate_check.py

    # Production launch-day check
    python scripts/launch_gate_check.py --base-url https://your-domain.com --logs /path/to/app.log

Exit code: 0 if all gates pass, 1 if any 🟡 or 🔴 remains.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# Force UTF-8 output on Windows so emoji status indicators render.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


@dataclass
class GateResult:
    name: str
    threshold: str
    actual: str
    status: str  # "pass" | "warn" | "fail"

    @property
    def symbol(self) -> str:
        return {"pass": "✅", "warn": "🟡", "fail": "🔴"}[self.status]


# ── Performance gate (local) ───────────────────────────────────────────────────


def perf_gate_local(base_url: str, api_key: str | None) -> GateResult:
    """Run 50 × jpg→webp 100 KB, compute p95, compare to 500 ms threshold."""
    if not api_key:
        return GateResult(
            "Perf P95 < 500 ms (local jpg→webp burst)",
            "P95 < 500 ms",
            "skipped (no API key — pass --api-key or set FILEMORPH_API_KEY)",
            "warn",
        )

    try:
        from PIL import Image
    except ImportError:
        return GateResult(
            "Perf P95 < 500 ms",
            "P95 < 500 ms",
            "skipped (Pillow not installed)",
            "warn",
        )

    img = Image.new("RGB", (700, 700))
    pixels = img.load()
    for x in range(700):
        for y in range(700):
            pixels[x, y] = ((x * 7 + y * 3) % 256, (x * 13 + y * 11) % 256, (x * 5 + y * 17) % 256)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    sample_bytes = buf.getvalue()

    durations: list[float] = []
    headers = {"X-API-Key": api_key}
    session = requests.Session()
    for _ in range(50):
        files = {"file": ("sample.jpg", sample_bytes, "image/jpeg")}
        data = {"target_format": "webp"}
        t0 = time.perf_counter()
        try:
            r = session.post(
                f"{base_url}/api/v1/convert", headers=headers, files=files, data=data, timeout=30
            )
        except requests.RequestException as exc:
            return GateResult(
                "Perf P95 < 500 ms (local jpg→webp burst)",
                "P95 < 500 ms",
                f"request failed: {exc}",
                "fail",
            )
        dt_ms = (time.perf_counter() - t0) * 1000
        if r.status_code != 200:
            return GateResult(
                "Perf P95 < 500 ms (local jpg→webp burst)",
                "P95 < 500 ms",
                f"http {r.status_code}: {r.text[:120]}",
                "fail",
            )
        durations.append(dt_ms)

    durations.sort()
    p50 = durations[len(durations) // 2]
    p95 = durations[int(len(durations) * 0.95)]
    p99 = durations[min(int(len(durations) * 0.99), len(durations) - 1)]
    status = "pass" if p95 < 500 else "fail"
    return GateResult(
        "Perf P95 < 500 ms (local jpg→webp burst)",
        "P95 < 500 ms",
        f"p50={p50:.0f}ms, p95={p95:.0f}ms, p99={p99:.0f}ms (n={len(durations)})",
        status,
    )


# ── Performance + error gate (live logs) ───────────────────────────────────────


def parse_log_file(path: Path, days: int = 7) -> tuple[list[dict], dict]:
    """Read JSON-lines log, return (matching records, summary)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    convert_records: list[dict] = []
    compress_records: list[dict] = []
    parse_errors = 0

    if not path.exists():
        return [], {"error": f"log file not found: {path}"}

    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                parse_errors += 1
                continue
            ts_str = rec.get("time") or rec.get("timestamp") or ""
            try:
                ts = datetime.strptime(ts_str.split(",")[0], "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue
            if ts < cutoff:
                continue
            op = rec.get("operation")
            if op == "convert":
                convert_records.append(rec)
            elif op == "compress":
                compress_records.append(rec)

    summary = {
        "convert_count": len(convert_records),
        "compress_count": len(compress_records),
        "parse_errors": parse_errors,
        "window_days": days,
    }
    return convert_records + compress_records, summary


def perf_gate_live(records: list[dict]) -> GateResult:
    durations = [
        r.get("duration_ms") for r in records if isinstance(r.get("duration_ms"), (int, float))
    ]
    if not durations:
        return GateResult(
            "Perf P95 < 500 ms (live last 7d)",
            "P95 < 500 ms",
            "no convert/compress records in window",
            "warn",
        )
    durations.sort()
    p50 = statistics.median(durations)
    p95 = durations[int(len(durations) * 0.95)]
    p99 = durations[min(int(len(durations) * 0.99), len(durations) - 1)]
    status = "pass" if p95 < 500 else "fail"
    return GateResult(
        "Perf P95 < 500 ms (live last 7d)",
        "P95 < 500 ms",
        f"p50={p50:.0f}ms, p95={p95:.0f}ms, p99={p99:.0f}ms (n={len(durations)})",
        status,
    )


def error_gate_live(records: list[dict]) -> GateResult:
    fails = [r for r in records if r.get("success") is False]
    n = len(records)
    if n == 0:
        return GateResult(
            "Error rate = 0% (live last 7d)",
            "0 errors / 7d",
            "no records — gate cannot be evaluated",
            "warn",
        )
    rate = len(fails) / n
    status = "pass" if not fails else "fail"
    return GateResult(
        "Error rate = 0% (live last 7d)",
        "0 errors / 7d",
        f"{len(fails)} fail / {n} total ({rate:.2%})",
        status,
    )


# ── Asset gate ─────────────────────────────────────────────────────────────────


def og_image_gate(repo_root: Path, base_url: str) -> GateResult:
    """OG-image must exist as a static asset and be 1200×630."""
    candidates = [
        repo_root / "app" / "static" / "og-image.png",
        repo_root / "app" / "static" / "og-image.jpg",
        repo_root / "app" / "static" / "img" / "og-image.png",
    ]
    found = next((p for p in candidates if p.exists()), None)
    if not found:
        # Try fetching via HTTP — maybe it's served from elsewhere
        try:
            r = requests.get(f"{base_url}/static/og-image.png", timeout=5)
            if r.status_code == 200:
                from io import BytesIO

                from PIL import Image

                img = Image.open(BytesIO(r.content))
                w, h = img.size
                if (w, h) == (1200, 630):
                    return GateResult(
                        "OG-Image 1200x630 asset",
                        "1200x630 PNG/JPG",
                        f"served at /static/og-image.png ({w}x{h}, {len(r.content) // 1024} KB)",
                        "pass",
                    )
                return GateResult(
                    "OG-Image 1200x630 asset",
                    "1200x630 PNG/JPG",
                    f"found but {w}x{h} (need 1200x630)",
                    "fail",
                )
        except Exception:
            pass
        return GateResult(
            "OG-Image 1200x630 asset",
            "1200x630 PNG/JPG",
            "not found in app/static/ — Phase C also reports missing og:image meta",
            "fail",
        )

    try:
        from PIL import Image

        img = Image.open(found)
        w, h = img.size
    except Exception as exc:
        return GateResult(
            "OG-Image 1200x630 asset",
            "1200x630 PNG/JPG",
            f"file exists but unreadable: {exc}",
            "fail",
        )
    size_kb = found.stat().st_size // 1024
    if (w, h) == (1200, 630):
        return GateResult(
            "OG-Image 1200x630 asset",
            "1200x630 PNG/JPG",
            f"{found.name}: {w}x{h}, {size_kb} KB",
            "pass",
        )
    return GateResult(
        "OG-Image 1200x630 asset",
        "1200x630 PNG/JPG",
        f"{found.name}: {w}x{h} (need 1200x630)",
        "fail",
    )


# ── Release / Stripe / health ──────────────────────────────────────────────────


def health_version_gate(base_url: str) -> GateResult:
    try:
        r = requests.get(f"{base_url}/api/v1/health", timeout=10)
    except requests.RequestException as exc:
        return GateResult(
            "/health version field",
            "version present",
            f"request failed: {exc}",
            "fail",
        )
    if r.status_code != 200:
        return GateResult(
            "/health version field",
            "version present",
            f"status {r.status_code}",
            "fail",
        )
    try:
        data = r.json()
    except json.JSONDecodeError:
        return GateResult(
            "/health version field",
            "version present",
            "non-JSON response",
            "fail",
        )
    version = data.get("version")
    if not version:
        return GateResult(
            "/health version field",
            "version present",
            "no `version` key in response",
            "fail",
        )
    return GateResult(
        "/health version field",
        "version present",
        f"version={version}, ffmpeg_available={data.get('ffmpeg_available')}",
        "pass",
    )


def stripe_env_gate() -> GateResult:
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret:
        return GateResult(
            "STRIPE_WEBHOOK_SECRET env var",
            "set in production env",
            "not set — webhook signature verification will fail",
            "fail",
        )
    if not secret.startswith("whsec_"):
        return GateResult(
            "STRIPE_WEBHOOK_SECRET env var",
            "set in production env",
            f"set but does not start with `whsec_` (length {len(secret)})",
            "warn",
        )
    return GateResult(
        "STRIPE_WEBHOOK_SECRET env var",
        "set in production env",
        f"set ({len(secret)} chars, whsec_* prefix)",
        "pass",
    )


def stripe_webhook_endpoint_gate(base_url: str) -> GateResult:
    """POST without a signature header — should get 400/401/403 (signature
    invalid/missing), NOT 404 (route absent)."""
    try:
        r = requests.post(f"{base_url}/api/v1/billing/webhook", json={}, timeout=10)
    except requests.RequestException as exc:
        return GateResult(
            "Stripe webhook endpoint exists",
            "POST returns 4xx (not 404)",
            f"request failed: {exc}",
            "fail",
        )
    if r.status_code == 404:
        return GateResult(
            "Stripe webhook endpoint exists",
            "POST returns 4xx (not 404)",
            "404 — endpoint not implemented",
            "fail",
        )
    if r.status_code in (400, 401, 403, 422):
        return GateResult(
            "Stripe webhook endpoint exists",
            "POST returns 4xx (not 404)",
            f"status {r.status_code} (route present, signature rejected — expected)",
            "pass",
        )
    return GateResult(
        "Stripe webhook endpoint exists",
        "POST returns 4xx (not 404)",
        f"status {r.status_code} — unusual but not absent",
        "warn",
    )


# ── Driver ─────────────────────────────────────────────────────────────────────


def run_local(base_url: str, api_key: str | None, repo_root: Path) -> list[GateResult]:
    return [
        health_version_gate(base_url),
        perf_gate_local(base_url, api_key),
        og_image_gate(repo_root, base_url),
        stripe_env_gate(),
        stripe_webhook_endpoint_gate(base_url),
    ]


def run_with_logs(log_path: Path) -> list[GateResult]:
    records, summary = parse_log_file(log_path)
    if "error" in summary:
        return [
            GateResult(
                "log parse",
                "log file readable",
                summary["error"],
                "fail",
            )
        ]
    return [
        perf_gate_live(records),
        error_gate_live(records),
    ]


def print_results(local_results: list[GateResult], live_results: list[GateResult]) -> int:
    print("\nHard-Launch-Gate Check\n")
    print("Local gates:\n")
    for r in local_results:
        print(f"  {r.symbol}  {r.name:<50}  threshold: {r.threshold:<22}  actual: {r.actual}")

    if live_results:
        print("\nLive gates (from log file):\n")
        for r in live_results:
            print(f"  {r.symbol}  {r.name:<50}  threshold: {r.threshold:<22}  actual: {r.actual}")

    all_results = local_results + live_results
    by = {"pass": 0, "warn": 0, "fail": 0}
    for r in all_results:
        by[r.status] += 1
    print(
        f"\nSummary: {by['pass']} pass / {by['warn']} warn / "
        f"{by['fail']} fail   (total {len(all_results)})"
    )
    return 0 if by["warn"] == 0 and by["fail"] == 0 else 1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default="http://localhost:8000", help="Origin to check")
    p.add_argument(
        "--api-key",
        default=os.environ.get("FILEMORPH_API_KEY", ""),
        help="API key for the perf-burst test (or set FILEMORPH_API_KEY env)",
    )
    p.add_argument(
        "--logs",
        default="",
        help="Path to production JSON-lines log file (enables live gates)",
    )
    p.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parent.parent),
        help="Repo root for asset path resolution",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root)
    local_results = run_local(args.base_url.rstrip("/"), args.api_key or None, repo_root)
    live_results: list[GateResult] = []
    if args.logs:
        live_results = run_with_logs(Path(args.logs))
    return print_results(local_results, live_results)


if __name__ == "__main__":
    sys.exit(main())
