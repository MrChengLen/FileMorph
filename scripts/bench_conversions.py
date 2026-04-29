#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Benchmark all registered conversion pairs via FastAPI TestClient.

Iterates over the converter registry (`app.converters.registry`), builds a
synthetic sample for each source format, posts it to `/api/v1/convert`, and
records server-side `duration_ms` from the wall-clock around the request.

CSV output (one row per pair × sample size):
    src,tgt,category,sample_size_kb,duration_ms,output_size_kb,success,error

Markdown summary appended to stdout — pairs sorted by duration_ms desc, plus
p50/p95/p99 across all pairs and per category. Self-hosters can run this on
their hardware to size disk + CPU.

Usage:
    python scripts/bench_conversions.py --output docs-internal/perf-snapshots/$(date +%Y-%m-%d).csv
    python scripts/bench_conversions.py --sample-sizes 100k --skip-video
    python scripts/bench_conversions.py --pairs jpg:webp,png:webp --iterations 20

Notes:
    - Audio + video samples require ffmpeg. If absent, those pairs are
      skipped (recorded as success=False, error="ffmpeg unavailable").
    - HEIC source samples require pillow-heif. If absent, pairs starting from
      heic/heif are skipped.
    - The bench uses TestClient — no uvicorn, no network — so duration
      reflects converter CPU only, not transport.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image as PILImage

# Make the repo importable when run from anywhere.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import os

os.environ.setdefault("RATELIMIT_ENABLED", "0")

import hashlib
import json

from fastapi.testclient import TestClient

from app.core import security as sec_module
from app.main import app


# ── Sample generation ──────────────────────────────────────────────────────────


def _entropy_image(size_px: int) -> PILImage.Image:
    """High-entropy RGB image — JPEG/WebP encode at expected real-world size."""
    from PIL import Image

    img = Image.new("RGB", (size_px, size_px))
    pixels = img.load()
    for x in range(size_px):
        for y in range(size_px):
            pixels[x, y] = (
                (x * 7 + y * 3) % 256,
                (x * 13 + y * 11) % 256,
                (x * 5 + y * 17) % 256,
            )
    return img


_IMAGE_TARGET_PX = {
    "100k": 700,  # ~100 KB JPEG q=85
    "1m": 2200,  # ~1 MB JPEG q=85
    "10m": 7000,  # ~10 MB JPEG q=85
}


def build_image_sample(src_fmt: str, size_label: str, tmp: Path) -> Path | None:
    """Build a sample image in `src_fmt` at approximately `size_label` bytes."""
    from PIL import Image

    px = _IMAGE_TARGET_PX[size_label]
    img = _entropy_image(px)
    path = tmp / f"sample_{size_label}.{src_fmt}"

    if src_fmt in ("heic", "heif"):
        try:
            import pillow_heif  # noqa: F401
        except ImportError:
            return None
        # pillow_heif uses Image.save with "HEIF" / "HEIC" format.
        try:
            img.save(str(path), format="HEIF", quality=85)
        except Exception:
            return None
        return path

    fmt_map = {
        "jpg": "JPEG",
        "jpeg": "JPEG",
        "png": "PNG",
        "webp": "WEBP",
        "bmp": "BMP",
        "tiff": "TIFF",
        "tif": "TIFF",
        "gif": "GIF",
        "ico": "ICO",
    }
    pil_fmt = fmt_map.get(src_fmt)
    if pil_fmt is None:
        return None

    try:
        if pil_fmt == "ICO":
            small = img.resize((128, 128))
            small.save(str(path), format=pil_fmt)
        elif pil_fmt == "GIF":
            small = img.resize((min(px, 1500), min(px, 1500)))
            small.convert("P", palette=Image.ADAPTIVE).save(str(path), format=pil_fmt)
        elif pil_fmt in ("JPEG", "WEBP"):
            img.save(str(path), format=pil_fmt, quality=85)
        else:
            img.save(str(path), format=pil_fmt)
    except Exception:
        return None
    return path


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


_AUDIO_DURATION_S = {"100k": 1, "1m": 8, "10m": 80}
_VIDEO_DURATION_S = {"100k": 1, "1m": 4, "10m": 12, "20m": 24}


def build_audio_sample(src_fmt: str, size_label: str, tmp: Path) -> Path | None:
    if not _ffmpeg_available():
        return None
    duration = _AUDIO_DURATION_S.get(size_label, 1)
    path = tmp / f"sample_{size_label}.{src_fmt}"
    # sine-wave audio — encodes deterministically across formats
    cmd = [
        "ffmpeg",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration}",
        "-y",
        "-loglevel",
        "error",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=30)
    if result.returncode != 0 or not path.exists():
        return None
    return path


def build_video_sample(src_fmt: str, size_label: str, tmp: Path) -> Path | None:
    if not _ffmpeg_available():
        return None
    duration = _VIDEO_DURATION_S.get(size_label, 2)
    path = tmp / f"sample_{size_label}.{src_fmt}"
    cmd = [
        "ffmpeg",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size=320x240:rate=30",
        "-y",
        "-loglevel",
        "error",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    if result.returncode != 0 or not path.exists():
        return None
    return path


def build_document_sample(src_fmt: str, size_label: str, tmp: Path) -> Path | None:
    text_lines = {"100k": 2_000, "1m": 20_000, "10m": 200_000}
    n = text_lines.get(size_label, 2_000)
    path = tmp / f"sample_{size_label}.{src_fmt}"

    if src_fmt == "txt":
        path.write_text("\n".join(f"line {i}: lorem ipsum dolor sit amet" for i in range(n)))
        return path
    if src_fmt == "md":
        body = "\n".join(
            f"## Section {i}\n\nlorem ipsum dolor sit amet, line {i}." for i in range(n // 4)
        )
        path.write_text(f"# Title\n\n{body}\n")
        return path
    if src_fmt == "docx":
        try:
            from docx import Document
        except ImportError:
            return None
        doc = Document()
        for i in range(min(n // 10, 5_000)):
            doc.add_paragraph(f"line {i}: lorem ipsum dolor sit amet")
        doc.save(str(path))
        return path
    if src_fmt == "pdf":
        try:
            from reportlab.lib.pagesizes import LETTER
            from reportlab.pdfgen import canvas
        except ImportError:
            return None
        c = canvas.Canvas(str(path), pagesize=LETTER)
        for i in range(min(n // 30, 1_000)):
            if i % 40 == 0 and i > 0:
                c.showPage()
            c.drawString(72, 720 - (i % 40) * 14, f"line {i}: lorem ipsum dolor sit amet")
        c.save()
        return path
    return None


def build_spreadsheet_sample(src_fmt: str, size_label: str, tmp: Path) -> Path | None:
    rows = {"100k": 5_000, "1m": 50_000, "10m": 500_000}
    n = rows.get(size_label, 5_000)
    path = tmp / f"sample_{size_label}.{src_fmt}"

    if src_fmt == "csv":
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "name", "value", "tag"])
            for i in range(n):
                w.writerow([i, f"row{i}", i * 1.5, f"tag{i % 50}"])
        return path
    if src_fmt == "json":
        rows_list = [
            {"id": i, "name": f"row{i}", "value": i * 1.5, "tag": f"tag{i % 50}"} for i in range(n)
        ]
        path.write_text(json.dumps(rows_list))
        return path
    if src_fmt == "xlsx":
        try:
            from openpyxl import Workbook
        except ImportError:
            return None
        wb = Workbook(write_only=True)
        ws = wb.create_sheet("Sheet1")
        ws.append(["id", "name", "value", "tag"])
        for i in range(min(n, 100_000)):  # xlsx row cap pragmatic limit
            ws.append([i, f"row{i}", i * 1.5, f"tag{i % 50}"])
        wb.save(str(path))
        return path
    return None


# ── Categorization ─────────────────────────────────────────────────────────────


_IMAGE_FMTS = {"jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif", "gif", "ico", "heic", "heif"}
_AUDIO_FMTS = {"mp3", "wav", "flac", "ogg", "m4a", "aac", "wma", "opus"}
_VIDEO_FMTS = {"mp4", "avi", "mov", "mkv", "webm", "flv", "wmv"}
_DOC_FMTS = {"txt", "md", "docx", "pdf", "html"}
_SHEET_FMTS = {"csv", "xlsx", "json"}


def categorize(src: str) -> str:
    if src in _IMAGE_FMTS:
        return "image"
    if src in _AUDIO_FMTS:
        return "audio"
    if src in _VIDEO_FMTS:
        return "video"
    if src in _DOC_FMTS:
        return "document"
    if src in _SHEET_FMTS:
        return "spreadsheet"
    return "other"


def build_sample(src: str, size_label: str, tmp: Path) -> Path | None:
    cat = categorize(src)
    if cat == "image":
        return build_image_sample(src, size_label, tmp)
    if cat == "audio":
        return build_audio_sample(src, size_label, tmp)
    if cat == "video":
        return build_video_sample(src, size_label, tmp)
    if cat == "document":
        return build_document_sample(src, size_label, tmp)
    if cat == "spreadsheet":
        return build_spreadsheet_sample(src, size_label, tmp)
    return None


# ── Test client setup ──────────────────────────────────────────────────────────

TEST_KEY = "bench-key-filemorph"


def setup_client() -> TestClient:
    """Mirror tests/conftest.py — write a temp api_keys.json and point security at it."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="fm_bench_"))
    keys_file = tmp_dir / "api_keys.json"
    key_hash = hashlib.sha256(TEST_KEY.encode()).hexdigest()
    keys_file.write_text(json.dumps({"keys": [key_hash]}))
    sec_module.settings.__dict__["api_keys_file"] = str(keys_file)
    return TestClient(app)


# ── Bench loop ─────────────────────────────────────────────────────────────────


def bench_pair(
    client: TestClient,
    src: str,
    tgt: str,
    sample_path: Path,
    iterations: int,
) -> tuple[float, int, bool, str]:
    """Returns (median_ms, output_size_kb, success, error)."""
    durations: list[float] = []
    output_size = 0
    headers = {"X-API-Key": TEST_KEY}
    sample_bytes = sample_path.read_bytes()

    for _ in range(iterations):
        files = {"file": (sample_path.name, sample_bytes, "application/octet-stream")}
        data = {"target_format": tgt}
        t0 = time.perf_counter()
        try:
            res = client.post("/api/v1/convert", headers=headers, files=files, data=data)
        except Exception as exc:
            return 0.0, 0, False, f"request failed: {exc}"
        dt_ms = (time.perf_counter() - t0) * 1000

        if res.status_code != 200:
            try:
                detail = res.json().get("detail", "")[:120]
            except Exception:
                detail = res.text[:120]
            return dt_ms, 0, False, f"http {res.status_code}: {detail}"
        durations.append(dt_ms)
        output_size = len(res.content)

    return statistics.median(durations), output_size // 1024, True, ""


def run_bench(
    pairs: list[tuple[str, str]],
    sample_sizes: list[str],
    iterations: int,
    csv_writer,
) -> list[dict]:
    """Run bench, write CSV rows, return aggregated results for markdown summary."""
    client = setup_client()
    tmp = Path(tempfile.mkdtemp(prefix="fm_bench_samples_"))
    sample_cache: dict[tuple[str, str], Path | None] = {}
    results: list[dict] = []

    total = len(pairs) * len(sample_sizes)
    done = 0

    for src, tgt in pairs:
        for size_label in sample_sizes:
            done += 1
            cache_key = (src, size_label)
            if cache_key not in sample_cache:
                sample_cache[cache_key] = build_sample(src, size_label, tmp)
            sample = sample_cache[cache_key]

            if sample is None:
                row = {
                    "src": src,
                    "tgt": tgt,
                    "category": categorize(src),
                    "sample_size_kb": _label_to_kb(size_label),
                    "duration_ms": 0.0,
                    "output_size_kb": 0,
                    "success": False,
                    "error": "sample build failed (deps missing or format unsupported)",
                }
                csv_writer.writerow(row)
                results.append(row)
                _progress(done, total, src, tgt, size_label, "skip")
                continue

            duration_ms, output_kb, success, error = bench_pair(
                client, src, tgt, sample, iterations
            )
            row = {
                "src": src,
                "tgt": tgt,
                "category": categorize(src),
                "sample_size_kb": sample.stat().st_size // 1024,
                "duration_ms": round(duration_ms, 1),
                "output_size_kb": output_kb,
                "success": success,
                "error": error,
            }
            csv_writer.writerow(row)
            results.append(row)
            tag = "ok" if success else "fail"
            _progress(done, total, src, tgt, size_label, f"{tag} {duration_ms:.0f}ms")

    shutil.rmtree(tmp, ignore_errors=True)
    return results


def _label_to_kb(label: str) -> int:
    return {"100k": 100, "1m": 1024, "10m": 10240, "20m": 20480}.get(label, 0)


def _progress(done: int, total: int, src: str, tgt: str, size: str, tag: str) -> None:
    print(f"[{done:>4}/{total}] {src:>5} -> {tgt:<5} {size:>4}  {tag}", file=sys.stderr)


# ── Markdown summary ───────────────────────────────────────────────────────────


def print_summary(results: list[dict]) -> None:
    successful = [r for r in results if r["success"]]
    if not successful:
        print("\n⚠️  No successful runs — see CSV `error` column.", file=sys.stderr)
        return

    print("\n## Benchmark Summary\n")

    by_cat: dict[str, list[float]] = defaultdict(list)
    for r in successful:
        by_cat[r["category"]].append(r["duration_ms"])

    print("### Per category (all sample sizes pooled)\n")
    print("| Category | n | median | p95 | p99 | max |")
    print("|---|---:|---:|---:|---:|---:|")
    for cat in sorted(by_cat):
        ds = sorted(by_cat[cat])
        n = len(ds)
        p50 = ds[n // 2]
        p95 = ds[min(int(n * 0.95), n - 1)]
        p99 = ds[min(int(n * 0.99), n - 1)]
        print(f"| {cat} | {n} | {p50:.0f} ms | {p95:.0f} ms | {p99:.0f} ms | {ds[-1]:.0f} ms |")

    print("\n### Slowest 20 pairs (sorted by duration desc)\n")
    print("| src -> tgt | sample KB | duration ms | output KB |")
    print("|---|---:|---:|---:|")
    slow = sorted(successful, key=lambda r: r["duration_ms"], reverse=True)[:20]
    for r in slow:
        print(
            f"| {r['src']} -> {r['tgt']} | {r['sample_size_kb']} | "
            f"{r['duration_ms']:.0f} | {r['output_size_kb']} |"
        )

    failed = [r for r in results if not r["success"]]
    if failed:
        print(f"\n### Failed / Skipped ({len(failed)})\n")
        # group by error message
        by_err: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for r in failed:
            by_err[r["error"]].append((r["src"], r["tgt"]))
        for err, pairs in by_err.items():
            sample = ", ".join(f"{s}->{t}" for s, t in pairs[:5])
            more = f" (+{len(pairs) - 5} more)" if len(pairs) > 5 else ""
            print(f"- **{err}**: {sample}{more}")


# ── CLI ────────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--sample-sizes",
        default="100k",
        help="Comma-separated: 100k,1m,10m,20m (default: 100k)",
    )
    p.add_argument(
        "--iterations", type=int, default=3, help="Iterations per pair (default 3, takes median)"
    )
    p.add_argument("--pairs", default="", help="Restrict to comma-separated src:tgt pairs")
    p.add_argument(
        "--skip-categories",
        default="",
        help="Comma-separated categories to skip (image|audio|video|document|spreadsheet)",
    )
    p.add_argument("--output", default="-", help="CSV output path (default: stdout)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    from app.converters.registry import get_supported_conversions

    supported = get_supported_conversions()
    all_pairs: list[tuple[str, str]] = [(s, t) for s, ts in supported.items() for t in ts]

    if args.pairs:
        wanted = {tuple(p.split(":")) for p in args.pairs.split(",") if ":" in p}
        all_pairs = [pair for pair in all_pairs if pair in wanted]

    skip_cats = {c.strip() for c in args.skip_categories.split(",") if c.strip()}
    if skip_cats:
        all_pairs = [(s, t) for s, t in all_pairs if categorize(s) not in skip_cats]

    sample_sizes = [s.strip() for s in args.sample_sizes.split(",") if s.strip()]

    print(
        f"Bench: {len(all_pairs)} pairs × {len(sample_sizes)} sample sizes × "
        f"{args.iterations} iterations = {len(all_pairs) * len(sample_sizes) * args.iterations} requests",
        file=sys.stderr,
    )

    if args.output == "-":
        out_handle = sys.stdout
    else:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_handle = out_path.open("w", newline="")

    fieldnames = [
        "src",
        "tgt",
        "category",
        "sample_size_kb",
        "duration_ms",
        "output_size_kb",
        "success",
        "error",
    ]
    writer = csv.DictWriter(out_handle, fieldnames=fieldnames)
    writer.writeheader()

    try:
        results = run_bench(all_pairs, sample_sizes, args.iterations, writer)
    finally:
        if out_handle is not sys.stdout:
            out_handle.close()

    print_summary(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
