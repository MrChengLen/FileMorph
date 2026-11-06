# SPDX-License-Identifier: AGPL-3.0-or-later
import io
import math
from pathlib import Path

from PIL import Image

from app.converters._metadata import icc_for, strip_metadata
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
# fits: the target can't be reached then, and the image keeps its size. (A
# colour profile that would make it so goes first, see _ICC_TARGET_SHARE.)
_RESIZE_QUALITY = 80
_RESIZE_MARGIN = 0.9
_MAX_RESIZE_FACTOR = 0.75
_RESIZE_ENCODES = 12
_MIN_EDGE_PX = 16
# A colour profile larger than this share of the target is dropped for it.
_ICC_TARGET_SHARE = 4


def compress_image(input_path: Path, output_path: Path, quality: int = 85) -> Path:
    """Compress an image by re-encoding at a lower quality.

    quality: 1 (worst) – 100 (best), for JPEG, WebP and AVIF. PNG and TIFF
    are lossless and come out the same whatever the quality: PNG packed at
    zlib's highest level (``optimize=True`` overrides ``compress_level``),
    TIFF with Deflate (see the TIFF branch). The web UI hides the slider for
    them (``LOSSLESS_COMPRESS_TYPES`` in ``app/static/js/app.js``).

    NEU-C.2: PII-bearing metadata (EXIF GPS, camera serial, XMP/IPTC
    creator) is stripped from the output by default — see
    ``app/converters/_metadata.py``. The ICC colour profile stays: PNG, TIFF
    and AVIF write it on their own, JPEG and WebP only when passed
    ``icc_profile``. The size estimate in ``app.js`` adds its bytes for a JPEG
    (``pillowIccBytes``).
    """
    quality = max(1, min(100, quality))
    ext = input_path.suffix.lstrip(".").lower()
    pil_fmt = _PIL_FORMAT.get(ext, "JPEG")

    img = open_image(input_path)
    if pil_fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    img = strip_metadata(img)

    if pil_fmt == "JPEG":
        img.save(
            output_path,
            format="JPEG",
            quality=quality,
            optimize=True,
            icc_profile=icc_for(img, "JPEG"),
        )
    elif pil_fmt == "PNG":
        # PNG compress_level 0-9: map quality 100→0, quality 1→9. optimize=True
        # packs at level 9 regardless, so the quality changes nothing here.
        compress_level = max(0, min(9, 9 - round(quality / 100 * 9)))
        img.save(output_path, format="PNG", compress_level=compress_level, optimize=True)
    elif pil_fmt == "WEBP":
        img.save(
            output_path, format="WEBP", quality=quality, method=6, icc_profile=icc_for(img, "WEBP")
        )
    elif pil_fmt == "AVIF":
        # Lossy; quality 1-100 maps to the AV1 quantizer. speed is the
        # libavif effort knob (0 slowest/best … 10 fastest); 6 keeps encode
        # cost reasonable on a request thread while staying well-compressed.
        img.save(
            output_path, format="AVIF", quality=quality, speed=6, icc_profile=icc_for(img, "AVIF")
        )
    elif pil_fmt == "TIFF" and img.mode == "1":
        # TIFF in black and white: the smaller of Group 4 (scanned text packs
        # best so) and Deflate (dithered pictures do).
        packed = []
        for compression in ("group4", "tiff_adobe_deflate"):
            buf = io.BytesIO()
            img.save(buf, format=pil_fmt, compression=compression)
            packed.append(buf.getvalue())
        output_path.write_bytes(min(packed, key=len))
    else:
        # TIFF. Saved without a compression it was raw pixels, larger than an
        # LZW or Deflate original. Deflate, with the horizontal predictor that
        # photo TIFFs from Photoshop, GIMP or libvips use — not for palette
        # images, which it makes larger.
        options = {} if img.mode == "P" else {"tiffinfo": {317: 2}}  # 317: Predictor
        img.save(output_path, format=pil_fmt, compression="tiff_adobe_deflate", **options)

    return output_path


def _encode_to_bytes(img: Image.Image, pil_fmt: str, quality: int) -> bytes:
    buf = io.BytesIO()
    if pil_fmt == "JPEG":
        img.save(
            buf, format="JPEG", quality=quality, optimize=True, icc_profile=icc_for(img, "JPEG")
        )
    elif pil_fmt == "AVIF":
        img.save(buf, format="AVIF", quality=quality, speed=6, icc_profile=icc_for(img, "AVIF"))
    else:
        img.save(buf, format="WEBP", quality=quality, method=6, icc_profile=icc_for(img, "WEBP"))
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
    # The target is the promise (an upload limit), the colour profile a
    # nicety: one that would take more than a quarter of it goes — a print
    # profile of some hundred KB, say. sRGB (3 KB) or Display P3 (under 1 KB)
    # stay for any target worth setting.
    if len(img.info.get("icc_profile") or b"") > target_bytes // _ICC_TARGET_SHARE:
        del img.info["icc_profile"]

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
