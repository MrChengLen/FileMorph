# SPDX-License-Identifier: AGPL-3.0-or-later
import io
import math
from pathlib import Path

from PIL import Image

from app.converters._metadata import strip_metadata
from app.core.image_hardening import open_image

# Register pillow-avif-plugin if available. Importing it registers AVIF
# encode+decode with Pillow; this module imports Pillow independently of the
# converter, so it must trigger the registration itself. Gate AVIF support on
# the import succeeding, exactly like the converter does.
try:
    import pillow_avif  # noqa: F401

    _avif_available = True
except ImportError:
    _avif_available = False

_SUPPORTED_FORMATS = ["jpg", "jpeg", "png", "webp", "tiff", "tif"]

_PIL_FORMAT = {
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "tiff": "TIFF",
    "tif": "TIFF",
}

# AVIF is lossy and quality-controlled, so it supports both quality-based and
# target-size (binary-search-on-quality) compression — added to both sets.
if _avif_available:
    _SUPPORTED_FORMATS.append("avif")
    _PIL_FORMAT["avif"] = "AVIF"

TARGET_SIZE_FORMATS = {"jpg", "jpeg", "webp"}
if _avif_available:
    TARGET_SIZE_FORMATS.add("avif")

# Target size is an upper bound: upload portals reject 5.1 MB at a 5 MB limit.
# When even quality 1 doesn't fit, the image is scaled down to where quality
# _RESIZE_QUALITY would fit — the byte count grows roughly with the pixel
# count — with _RESIZE_MARGIN of headroom, and searched again. A smaller image
# at a good quality looks better than one shrunk only just enough for
# quality 1. Each round shrinks to at most _MAX_RESIZE_FACTOR, never below a
# short edge of _MIN_EDGE_PX, and all rounds together spend at most
# _RESIZE_ENCODES encodes. Scaling is skipped when not even the smallest size
# fits (an image carrying a large colour profile, say): the target can't be
# reached then, and the image keeps its size.
_RESIZE_QUALITY = 80
_RESIZE_MARGIN = 0.9
_MAX_RESIZE_FACTOR = 0.75
_RESIZE_ENCODES = 12
_MIN_EDGE_PX = 16


def compress_image(input_path: Path, output_path: Path, quality: int = 85) -> Path:
    """Compress an image by re-encoding at a lower quality.

    quality: 1 (worst) – 100 (best). For PNG (lossless) the quality
    parameter controls compression speed/level rather than visual quality.

    NEU-C.2: PII-bearing metadata (EXIF GPS, camera serial, XMP/IPTC
    creator) is stripped from the output by default — see
    ``app/converters/_metadata.py``. ICC colour profile is preserved.
    """
    quality = max(1, min(100, quality))
    ext = input_path.suffix.lstrip(".").lower()
    pil_fmt = _PIL_FORMAT.get(ext, "JPEG")

    img = open_image(input_path)
    if pil_fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    img = strip_metadata(img)

    if pil_fmt == "JPEG":
        img.save(output_path, format="JPEG", quality=quality, optimize=True)
    elif pil_fmt == "PNG":
        # PNG compress_level 0-9: map quality 100→0, quality 1→9
        compress_level = max(0, min(9, 9 - round(quality / 100 * 9)))
        img.save(output_path, format="PNG", compress_level=compress_level, optimize=True)
    elif pil_fmt == "WEBP":
        img.save(output_path, format="WEBP", quality=quality, method=6)
    elif pil_fmt == "AVIF":
        # Lossy; quality 1-100 maps to the AV1 quantizer. speed is the
        # libavif effort knob (0 slowest/best … 10 fastest); 6 keeps encode
        # cost reasonable on a request thread while staying well-compressed.
        img.save(output_path, format="AVIF", quality=quality, speed=6)
    else:
        img.save(output_path, format=pil_fmt)

    return output_path


def _encode_to_bytes(img: Image.Image, pil_fmt: str, quality: int) -> bytes:
    buf = io.BytesIO()
    if pil_fmt == "JPEG":
        img.save(buf, format="JPEG", quality=quality, optimize=True)
    elif pil_fmt == "AVIF":
        img.save(buf, format="AVIF", quality=quality, speed=6)
    else:
        img.save(buf, format="WEBP", quality=quality, method=6)
    return buf.getvalue()


def _best_fit(
    img: Image.Image, pil_fmt: str, target_bytes: int, tolerance: float, max_iterations: int
) -> tuple[int | None, bytes | None, int]:
    """The highest quality whose encoding fits ``target_bytes``.

    Returns ``(quality, data, encodes)``; quality and data are ``None`` when
    not even quality 1 fits. The search stops early on a fit within
    ``tolerance`` below the target.
    """
    # Shortcut: a high-quality re-encode that already fits is shipped as is.
    probe = _encode_to_bytes(img, pil_fmt, 95)
    if len(probe) <= target_bytes:
        return 95, probe, 1

    lower = int(target_bytes * (1 - tolerance))
    low, high = 1, 94
    encodes = 1
    best_q: int | None = None
    best: bytes | None = None
    lowest_tried = 95
    while low <= high and encodes <= max_iterations:
        q = (low + high) // 2
        data = _encode_to_bytes(img, pil_fmt, q)
        encodes += 1
        lowest_tried = min(lowest_tried, q)
        if len(data) <= target_bytes:
            best_q, best = q, data
            if len(data) >= lower:
                break
            low = q + 1
        else:
            high = q - 1

    if best is None and lowest_tried > 1:
        # The search ran out of iterations before trying quality 1.
        data = _encode_to_bytes(img, pil_fmt, 1)
        encodes += 1
        if len(data) <= target_bytes:
            best_q, best = 1, data
    return best_q, best, encodes


def _scaled(img: Image.Image, pil_fmt: str, factor: float) -> Image.Image:
    """``img`` scaled by ``factor`` (< 1), keeping a short edge of at least
    ``_MIN_EDGE_PX``."""
    if img.mode in ("P", "PA", "1") or img.mode.startswith("I;16"):
        # Palette and bilevel images resample only with NEAREST, and reduce()
        # has no 16-bit modes; JPEG takes no alpha.
        keep_alpha = pil_fmt != "JPEG" and img.has_transparency_data
        img = img.convert("RGBA" if keep_alpha else "RGB")
    size = (
        max(_MIN_EDGE_PX, round(img.width * factor)),
        max(_MIN_EDGE_PX, round(img.height * factor)),
    )
    return img.resize(size, Image.Resampling.LANCZOS, reducing_gap=2.0)


def compress_image_to_target(
    input_path: Path,
    output_path: Path,
    target_bytes: int,
    tolerance: float = 0.03,
    max_iterations: int = 8,
) -> dict:
    """Write the best-quality encoding that is at most ``target_bytes``.

    Binary-searches the quality (1-100) for the highest one that fits,
    stopping early on a fit within ``tolerance`` below the target. When not
    even quality 1 fits, the image is scaled down and searched again (see
    ``_RESIZE_QUALITY``). The output stays above the target only when not
    even the smallest size — short edge ``_MIN_EDGE_PX``, quality 1 — fits;
    then the unscaled image is written at quality 1 and ``converged`` is
    false.

    Returns: {"final_quality": int, "achieved_bytes": int, "iterations": int,
              "converged": bool, "resized_to": (width, height) | None}.
    ``converged`` means the output is at most ``target_bytes``; ``resized_to``
    is the new pixel size when the image was scaled down.

    Only lossy formats supported (JPEG/WebP/AVIF) — PNG/TIFF are lossless
    and quality does not control size meaningfully. Caller must reject other
    formats before invoking.
    """
    ext = input_path.suffix.lstrip(".").lower()
    if ext not in TARGET_SIZE_FORMATS:
        raise ValueError(
            f"compress_image_to_target only supports lossy formats (JPEG/WebP/AVIF), got {ext!r}"
        )
    pil_fmt = _PIL_FORMAT[ext]

    img = open_image(input_path)
    if pil_fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    # NEU-C.2: strip PII before any encode pass — applies to every probe
    # in the binary search, not just the final write.
    img = strip_metadata(img)

    quality, data, iterations = _best_fit(img, pil_fmt, target_bytes, tolerance, max_iterations)
    resized_to: tuple[int, int] | None = None
    if data is None:
        # Not even quality 1 fits. Scaling helps only if the smallest size does.
        shrink = _MIN_EDGE_PX / min(img.size)
        smallest = _scaled(img, pil_fmt, shrink) if shrink < 1 else img
        floor = _encode_to_bytes(smallest, pil_fmt, 1)
        iterations += 1
        if len(floor) > target_bytes:
            # Unreachable (a large colour profile, say): a thumbnail that still
            # misses the target helps no one, so keep the size at quality 1.
            quality, data = 1, floor
            if smallest is not img:
                data = _encode_to_bytes(img, pil_fmt, 1)
                iterations += 1
        else:
            budget = _RESIZE_ENCODES
            while data is None and budget > 2:
                anchor = len(_encode_to_bytes(img, pil_fmt, _RESIZE_QUALITY))
                iterations += 1
                budget -= 1
                factor = min(_MAX_RESIZE_FACTOR, math.sqrt(target_bytes * _RESIZE_MARGIN / anchor))
                factor = max(factor, _MIN_EDGE_PX / min(img.size))
                if factor >= 1:
                    break
                img = _scaled(img, pil_fmt, factor)
                resized_to = img.size
                # _best_fit spends up to two encodes beyond its search steps.
                quality, data, encodes = _best_fit(
                    img, pil_fmt, target_bytes, tolerance, min(max_iterations, budget - 2)
                )
                iterations += encodes
                budget -= encodes
            if data is None:
                # The budget ran out before a larger size fitted; the smallest does.
                quality, data, resized_to = 1, floor, smallest.size
    output_path.write_bytes(data)
    return {
        "final_quality": quality,
        "achieved_bytes": len(data),
        "iterations": iterations,
        "converged": len(data) <= target_bytes,
        "resized_to": resized_to,
    }
