# SPDX-License-Identifier: AGPL-3.0-or-later
"""PDF compress-to-target — a "Morph > Convert" structural operation.

Shrink a PDF toward a caller-given byte budget by **recompressing its
embedded raster images**. Mirrors the shape of
``app/compressors/image.py::compress_image_to_target``: a binary-search on
a single global JPEG quality knob until the whole document fits the target
(within tolerance) or quality bottoms out. Returns a result dict the route
layer turns into structured logs + response headers.

What it touches — and what it deliberately doesn't
--------------------------------------------------
PDF size is dominated by embedded photos far more often than by text or
vector paths. So the lever here is the image XObjects: each true-colour /
grayscale image stream is decoded once (via pikepdf → Pillow) and
re-encoded as JPEG at a trial quality. Text, fonts, and vector content are
left byte-for-byte intact — page count and every glyph survive.

Images we leave alone (honest scope, not a bug):

* image masks / stencil masks (``/ImageMask``) and 1-bit images — JPEG
  can't represent them and they're already tiny;
* indexed / palette images — re-encoding to JPEG would blow up the size
  and wreck the palette;
* images carrying a soft mask (``/SMask``, i.e. alpha) — DCTDecode has no
  alpha channel, so recompressing would silently drop transparency.

Honest limit for image-poor PDFs
--------------------------------
A text/vector-only PDF (or one whose images are all in the skip set) has
nothing for this lever to grab. Rather than fail or claim impossible
compression, the engine re-saves a valid PDF (same pages, same content)
and reports ``converged=False`` with ``recompressible_images=0``. The
route surfaces that to the caller via headers/logs so the UI can say
"already optimal — no large images to shrink" instead of pretending.

Why pikepdf is imported lazily
------------------------------
Same Windows DLL-load ordering issue documented in
``app/converters/pdfa.py``: pikepdf bundles libqpdf, and importing it at
module load (before FastAPI has finished bootstrapping the auth route's
native deps) can segfault on Windows local-dev. Deferring the import to
call time sidesteps it. The blocking pikepdf/Pillow work runs under
``asyncio.to_thread`` in the route, identical to every other converter.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    import pikepdf as pikepdf_mod

logger = logging.getLogger(__name__)

# Quality ladder for the binary search. We never probe above this on the
# first pass — a PDF whose images are already JPEG-compressed gains little
# from re-encoding at 95, and starting lower keeps the search short.
_MAX_QUALITY = 90
_MIN_QUALITY = 20

# Below this, JPEG artefacts dominate and further size wins are marginal;
# the floor keeps a tiny-target request from producing visual mush while
# still honestly reporting ``converged=False``.
_DEFAULT_FLOOR = _MIN_QUALITY

# --- Working-set ceiling (DoS hardening) -------------------------------------
# ``_collect_decoded`` holds every recompressible image as a decoded
# ``PIL.Image`` simultaneously so the binary search can re-encode each probe
# without re-decoding. That makes peak memory a function of the *sum* of the
# images' pixel areas — a crafted PDF packing many large image XObjects could
# pin the worker into tens of GB of RGB buffers, the same warn-but-continue
# decompression-bomb class that ``app/core/image_hardening.py`` closes for
# single images. (Pillow's per-image ``MAX_IMAGE_PIXELS`` guard fires per
# decode, but nothing bounds the *aggregate* across many images held at once.)
#
# So before decoding anything we sum the declared ``/Width × /Height`` of the
# recompressible images (read straight from the XObject dict — no decode) and,
# if the document is over either ceiling, take the honest no-op path: re-save a
# valid, unchanged PDF and report ``converged=False`` / ``final_quality=None``
# rather than decoding everything. Two complementary caps:
#
#   * a total decoded-pixel budget (3 bytes/px RGB → ~1.5 GB peak at the
#     ceiling, well under a worker's headroom), and
#   * a hard count cap so thousands of tiny images can't each cost a Pillow
#     object + JPEG re-encode per probe.
#
# Generous enough that any legitimate scan/brochure PDF passes untouched.
_MAX_TOTAL_DECODE_PIXELS = 500_000_000  # ~500 megapixels summed across images
_MAX_RECOMPRESSIBLE_IMAGES = 2_000


class _DecodedImage:
    """A recompressible image XObject decoded once for repeated re-encoding.

    Holding the decoded ``PIL.Image`` lets the binary search probe many
    qualities without re-running the (expensive) decode each iteration.
    ``obj`` is the live pikepdf stream object we rewrite in place once the
    search settles on a final quality.
    """

    __slots__ = ("obj", "pil")

    def __init__(self, obj: "pikepdf_mod.Object", pil: Image.Image) -> None:
        self.obj = obj
        self.pil = pil


def _iter_image_xobjects(pdf: "pikepdf_mod.Pdf"):
    """Yield every distinct image XObject stream in the document.

    Walks each page's ``/Resources/XObject``. De-duplicates by object id so
    an image referenced from several pages (a repeated logo/letterhead) is
    only recompressed once — recompressing a shared stream twice would
    double-encode it and corrupt the second reference.
    """
    import pikepdf

    seen: set = set()
    for page in pdf.pages:
        resources = page.get("/Resources")
        if resources is None:
            continue
        xobjects = resources.get("/XObject")
        if xobjects is None:
            continue
        for obj in xobjects.values():
            if obj.get("/Subtype") != pikepdf.Name("/Image"):
                continue
            try:
                key = obj.objgen  # (num, gen) — stable identity for an indirect object
            except Exception:
                key = id(obj)
            if key in seen:
                continue
            seen.add(key)
            yield obj


def _is_recompressible(obj: "pikepdf_mod.Object", pim) -> bool:
    """Decide whether a JPEG re-encode is safe + useful for this image.

    Skips the classes JPEG can't faithfully carry (see module docstring):
    stencil/image masks, indexed/palette images, and anything with a soft
    mask (alpha). Everything else (RGB / grayscale photos, whether stored
    as DCTDecode or FlateDecode) is fair game.
    """
    import pikepdf

    if obj.get("/ImageMask"):
        return False
    if "/SMask" in obj:
        return False
    if "/Mask" in obj:
        return False
    try:
        if pim.image_mask:
            return False
        if pim.indexed:
            return False
        if pim.bits_per_component != 8:
            return False
    except (AttributeError, NotImplementedError):
        # pikepdf can't introspect an exotic colourspace — leave it alone
        # rather than risk a lossy/incorrect re-encode.
        return False
    # Only modes Pillow can re-encode as a plain JPEG.
    if pim.colorspace not in (pikepdf.Name("/DeviceRGB"), pikepdf.Name("/DeviceGray")):
        return False
    return True


def _exceeds_working_set(pdf: "pikepdf_mod.Pdf") -> bool:
    """True if the recompressible images would blow the decode working set.

    Cheap pre-flight: walks the same recompressible XObjects ``_collect_decoded``
    would decode, but only reads their declared ``/Width × /Height`` from the
    dict — *no pixel decode*. Returns ``True`` as soon as the running count or
    summed pixel area crosses a ceiling, so the caller can bail to the honest
    no-op path before materialising a single ``PIL.Image``.

    A missing/garbage dimension on an image is treated as 0 here (the actual
    decode in ``_collect_decoded`` is independently guarded by Pillow's
    per-image ``MAX_IMAGE_PIXELS``); this guard only exists to bound the
    *aggregate* the search holds at once.
    """
    from pikepdf import PdfImage

    count = 0
    total_pixels = 0
    for obj in _iter_image_xobjects(pdf):
        try:
            pim = PdfImage(obj)
            if not _is_recompressible(obj, pim):
                continue
        except Exception:  # noqa: BLE001 — unintrospectable image: skip, like _collect_decoded
            continue
        count += 1
        if count > _MAX_RECOMPRESSIBLE_IMAGES:
            return True
        try:
            w = int(obj.get("/Width", 0))
            h = int(obj.get("/Height", 0))
        except (TypeError, ValueError):
            w = h = 0
        total_pixels += max(0, w) * max(0, h)
        if total_pixels > _MAX_TOTAL_DECODE_PIXELS:
            return True
    return False


def _collect_decoded(pdf: "pikepdf_mod.Pdf") -> list[_DecodedImage]:
    """Decode every recompressible image once; return them for re-encoding.

    A decode that raises (corrupt stream, unsupported predictor) is skipped
    with a warning rather than aborting the whole compress — one bad image
    shouldn't sink an otherwise-shrinkable document.
    """
    from pikepdf import PdfImage

    decoded: list[_DecodedImage] = []
    for obj in _iter_image_xobjects(pdf):
        pim = PdfImage(obj)
        if not _is_recompressible(obj, pim):
            continue
        try:
            pil = pim.as_pil_image()
        except Exception as exc:  # noqa: BLE001 — any decode failure → skip this image
            logger.warning("pdf compress: skipping undecodable image (%s)", exc)
            continue
        if pil.mode not in ("RGB", "L"):
            pil = pil.convert("RGB")
        decoded.append(_DecodedImage(obj, pil))
    return decoded


def _encode_jpeg(pil: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _apply_quality(decoded: list[_DecodedImage], quality: int) -> None:
    """Rewrite every decoded image's stream at ``quality`` (in place)."""
    import pikepdf

    for d in decoded:
        jpeg = _encode_jpeg(d.pil, quality)
        # Replace the stream contents and declare DCTDecode. write() resets
        # any prior filter chain (e.g. a Flate-stored original becomes a
        # JPEG), so we also drop a stale /DecodeParms that no longer applies.
        d.obj.write(jpeg, filter=pikepdf.Name("/DCTDecode"))
        if "/DecodeParms" in d.obj:
            del d.obj["/DecodeParms"]


def _save_bytes(pdf: "pikepdf_mod.Pdf") -> bytes:
    """Serialise the current PDF state to bytes for a size probe."""
    buf = io.BytesIO()
    # object_stream_mode=generate compacts the xref into object streams —
    # the smallest honest container for a given content set. linearize is
    # off (it adds bytes for fast-web-view we don't need here).
    import pikepdf

    pdf.save(buf, object_stream_mode=pikepdf.ObjectStreamMode.generate, linearize=False)
    return buf.getvalue()


def compress_pdf_to_target(
    input_path: Path,
    output_path: Path,
    target_bytes: int,
    tolerance: float = 0.05,
    max_iterations: int = 7,
    quality_floor: int = _DEFAULT_FLOOR,
) -> dict:
    """Shrink a PDF toward ``target_bytes`` by recompressing its images.

    Binary-searches a single global JPEG quality (``_MIN_QUALITY`` ..
    ``_MAX_QUALITY``) applied to every recompressible image, re-saving and
    measuring the whole document each probe, until the output is within
    ``±tolerance`` of the target (or quality bottoms out at
    ``quality_floor``). Text, fonts and vector content are preserved; page
    count is never altered.

    Returns (mirrors ``compress_image_to_target`` + PDF-specific fields)::

        {
            "final_quality": int | None,   # None when nothing to recompress
            "achieved_bytes": int,         # output size on disk
            "iterations": int,
            "converged": bool,             # reached target within tolerance
            "recompressible_images": int,  # how many images we could touch
        }

    Honest limits (see module docstring): a PDF with no recompressible
    images is re-saved unchanged-in-content and reported
    ``converged=False`` / ``recompressible_images=0`` — never an error and
    never a false claim of compression.

    Lazy ``import pikepdf`` — see module docstring for the Windows DLL
    ordering reason.
    """
    import pikepdf

    if target_bytes <= 0:
        raise ValueError("target_bytes must be positive")

    with pikepdf.open(str(input_path)) as pdf:
        # --- DoS guard: bail before decoding an oversized working set. ----
        # A crafted image-rich PDF whose recompressible images sum past the
        # decode ceiling would OOM the worker in _collect_decoded (which holds
        # every decoded image at once). Treat it like the image-poor case: a
        # valid, content-unchanged re-save, honestly reported as not converged
        # with nothing recompressed — never decode the whole document.
        if _exceeds_working_set(pdf):
            logger.warning("pdf compress: working set exceeds decode ceiling — skipping recompress")
            data = _save_bytes(pdf)
            output_path.write_bytes(data)
            return {
                "final_quality": None,
                "achieved_bytes": len(data),
                "iterations": 0,
                "converged": False,
                "recompressible_images": 0,
            }

        decoded = _collect_decoded(pdf)
        n_images = len(decoded)

        # --- Honest no-op path: nothing this lever can grab. -------------
        if n_images == 0:
            data = _save_bytes(pdf)
            output_path.write_bytes(data)
            return {
                "final_quality": None,
                "achieved_bytes": len(data),
                "iterations": 0,
                "converged": False,
                "recompressible_images": 0,
            }

        upper = int(target_bytes * (1 + tolerance))
        lower = int(target_bytes * (1 - tolerance))

        # --- Shortcut: a top-quality re-encode already fits the target. --
        # (Many "target" requests are generous; don't degrade needlessly.)
        _apply_quality(decoded, _MAX_QUALITY)
        probe = _save_bytes(pdf)
        if len(probe) <= upper:
            output_path.write_bytes(probe)
            return {
                "final_quality": _MAX_QUALITY,
                "achieved_bytes": len(probe),
                "iterations": 1,
                "converged": True,
                "recompressible_images": n_images,
            }

        # --- Binary-search the quality knob. -----------------------------
        low, high = quality_floor, _MAX_QUALITY
        iterations = 1  # the shortcut probe above counts as iteration 1
        best_q: int | None = None
        best_bytes: bytes | None = None

        while low <= high and iterations < max_iterations:
            iterations += 1
            q = (low + high) // 2
            _apply_quality(decoded, q)
            data = _save_bytes(pdf)
            size = len(data)

            if size <= upper:
                # Acceptable upper bound — record best-so-far.
                best_q, best_bytes = q, data
                if size >= lower:
                    # Inside the tolerance band — done.
                    output_path.write_bytes(data)
                    return {
                        "final_quality": q,
                        "achieved_bytes": size,
                        "iterations": iterations,
                        "converged": True,
                        "recompressible_images": n_images,
                    }
                # Under the band — we can afford higher quality.
                low = q + 1
            else:
                # Over budget — drop quality.
                high = q - 1

        if best_bytes is not None:
            output_path.write_bytes(best_bytes)
            return {
                "final_quality": best_q,
                "achieved_bytes": len(best_bytes),
                "iterations": iterations,
                "converged": False,
                "recompressible_images": n_images,
            }

        # --- Even the quality floor overshot the target. -----------------
        # Ship the smallest we can honestly produce; report not-converged.
        _apply_quality(decoded, quality_floor)
        floor_bytes = _save_bytes(pdf)
        output_path.write_bytes(floor_bytes)
        return {
            "final_quality": quality_floor,
            "achieved_bytes": len(floor_bytes),
            "iterations": iterations + 1,
            "converged": False,
            "recompressible_images": n_images,
        }
