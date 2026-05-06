import io
from pathlib import Path

from PIL import Image

from app.converters._metadata import strip_metadata

_SUPPORTED_FORMATS = ["jpg", "jpeg", "png", "webp", "tiff", "tif"]

_PIL_FORMAT = {
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "tiff": "TIFF",
    "tif": "TIFF",
}

TARGET_SIZE_FORMATS = {"jpg", "jpeg", "webp"}


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

    img = Image.open(input_path)
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
    else:
        img.save(output_path, format=pil_fmt)

    return output_path


def _encode_to_bytes(img: Image.Image, pil_fmt: str, quality: int) -> bytes:
    buf = io.BytesIO()
    if pil_fmt == "JPEG":
        img.save(buf, format="JPEG", quality=quality, optimize=True)
    else:
        img.save(buf, format="WEBP", quality=quality, method=6)
    return buf.getvalue()


def compress_image_to_target(
    input_path: Path,
    output_path: Path,
    target_bytes: int,
    tolerance: float = 0.03,
    max_iterations: int = 8,
) -> dict:
    """Binary-search on quality (1-100) until output is within ±tolerance
    of target_bytes, or quality bottoms out.

    Returns: {"final_quality": int, "achieved_bytes": int,
              "iterations": int, "converged": bool}.

    Only JPEG/WebP supported — PNG/TIFF are lossless and quality does not
    control size meaningfully. Caller must reject other formats before
    invoking.
    """
    ext = input_path.suffix.lstrip(".").lower()
    if ext not in TARGET_SIZE_FORMATS:
        raise ValueError(f"compress_image_to_target only supports JPEG/WebP, got {ext!r}")
    pil_fmt = _PIL_FORMAT[ext]

    img = Image.open(input_path)
    if pil_fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    # NEU-C.2: strip PII before any encode pass — applies to every probe
    # in the binary search, not just the final write.
    img = strip_metadata(img)

    # Shortcut: if a high-quality re-encode is already within target, ship it.
    probe = _encode_to_bytes(img, pil_fmt, 95)
    if len(probe) <= target_bytes:
        output_path.write_bytes(probe)
        return {
            "final_quality": 95,
            "achieved_bytes": len(probe),
            "iterations": 1,
            "converged": True,
        }

    low, high = 1, 100
    iterations = 0
    best_q: int | None = None
    best_bytes: bytes | None = None
    upper = int(target_bytes * (1 + tolerance))
    lower = int(target_bytes * (1 - tolerance))

    while low <= high and iterations < max_iterations:
        iterations += 1
        q = (low + high) // 2
        encoded = _encode_to_bytes(img, pil_fmt, q)
        size = len(encoded)

        if size <= upper:
            # Acceptable upper-bound — record as best-so-far.
            best_q = q
            best_bytes = encoded
            if size >= lower:
                # Inside tolerance band — done.
                output_path.write_bytes(encoded)
                return {
                    "final_quality": q,
                    "achieved_bytes": size,
                    "iterations": iterations,
                    "converged": True,
                }
            # Below tolerance band — try higher quality.
            low = q + 1
        else:
            # Over budget — try lower quality.
            high = q - 1

    if best_bytes is not None:
        output_path.write_bytes(best_bytes)
        return {
            "final_quality": best_q or 1,
            "achieved_bytes": len(best_bytes),
            "iterations": iterations,
            "converged": False,
        }

    # Even q=1 exceeded target — ship the smallest we can produce.
    fallback = _encode_to_bytes(img, pil_fmt, 1)
    output_path.write_bytes(fallback)
    return {
        "final_quality": 1,
        "achieved_bytes": len(fallback),
        "iterations": iterations + 1,
        "converged": False,
    }
