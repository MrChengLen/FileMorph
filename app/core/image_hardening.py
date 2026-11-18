# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pillow hardening — settings and helpers for decoding uploaded images.

Pillow ships two thresholds on ``Image.MAX_IMAGE_PIXELS``:

- pixel-count above the threshold → ``DecompressionBombWarning`` (the
  default behaviour is *warn but continue decoding*),
- pixel-count above 2× the threshold → ``DecompressionBombError``
  raised synchronously, decode aborted.

A warning that doesn't halt the worker is a denial-of-service vector for
a file-conversion service: a 200 kB PNG whose IHDR claims 60 000 × 60 000
pixels (~3.6 gigapixels) coasts past every input-size check but pins the
worker for tens of seconds decoding into ~14 GB of RGBA memory. The
output-cap guard (``app/core/quotas.py``) would catch the result *after*
the decode, by which point the host has already paid the cost.

This module flips the warning to a hard error at import time so every
``Image.open(...)`` call site in the codebase fails fast and identically.
The chosen threshold matches Pillow's default (~89 megapixels —
``178 956 970`` would be the 2× ceiling). Tier-aware overrides go via the
``FILEMORPH_IMAGE_MAX_MEGAPIXELS`` env var; self-hosters with
explicit large-image use cases (high-res scans, GIS, microscopy)
bump it.

The resulting ``DecompressionBombError`` is a ``ValueError`` subclass; the
route handlers in ``app/api/routes/convert.py`` and ``compress.py`` catch
it specifically and emit HTTP 400 with
``X-FileMorph-Error-Code: decompression_bomb`` so the UI can render a
distinct error rather than the generic "Conversion failed" message.

Threat model reference: PT-008 territory of
``docs/security-pentest-report.md`` (the static-review item that flagged
the warn-but-continue default). The companion guard for output-size is
in ``app/core/quotas.py`` (per-tier output cap) — that one rejects *after*
encoding; this one rejects *before* decoding.

Code that opens an uploaded image uses ``open_image`` rather than
``Image.open``: Pillow then tries only the readers for the formats FileMorph
supports (``IMAGE_INPUT_FORMATS``), and reads the pixels instead of mapping
the file into memory — an uncompressed picture half a row at a time at least
(``read_in_rows``). A file none of them recognises becomes an
``InvalidInputError`` with a fixed message, which the routes answer with
HTTP 400 and ``X-FileMorph-Error-Code: invalid_input``; so does an icon
whose BMP picture is wider than an icon can be.

Pillow reads EPS by running Ghostscript, an external PostScript
interpreter. FileMorph converts no EPS, so Pillow never needs it:
``apply_hardening`` makes ``EpsImagePlugin`` treat Ghostscript as missing,
whatever is installed, and an EPS image then fails to load. The PDF/A
converter runs Ghostscript itself (``app/converters/_ghostscript.py``) and
is not affected.

Import order matters: ``import app.core.image_hardening`` must run *before*
the first ``Image.open(...)`` call in the application path. The current
chain is ``app/main.py → from app.api.routes import …`` which imports the
converter modules; importing this from ``app/main.py`` at module top puts
the warning filter in place before any route module runs.
"""

from __future__ import annotations

import os
import warnings
import weakref
from typing import IO

from PIL import EpsImagePlugin, Image, ImageFile, UnidentifiedImageError

from app.converters.base import InvalidInputError

# Default matches Pillow's stock threshold so existing legitimate uploads
# keep working unchanged. The 2× ceiling lives below at
# ``DecompressionBombError``-raising time (Pillow internal); we tighten
# the *warning* threshold to also raise.
_DEFAULT_MAX_MEGAPIXELS = 89

# The image formats FileMorph reads, as Pillow reader IDs: the inputs of
# app/converters/image.py (avif bmp gif heic heif ico jpeg jpg png tif tiff
# webp). A multi-picture JPEG (as phone cameras write them) opens through the
# "JPEG" reader and then reports format "MPO"; an animated PNG opens through
# "PNG". "MPO" is no reader ID, so it isn't listed. ``open_image`` passes only
# registered IDs (``Image.open`` raises KeyError on others), which drops
# "HEIF" when pillow-heif isn't installed.
IMAGE_INPUT_FORMATS = ("AVIF", "BMP", "GIF", "HEIF", "ICO", "JPEG", "PNG", "TIFF", "WEBP")

_UNREADABLE_IMAGE = (
    "Could not read the image: it is damaged or not in a supported image format. "
    "Save it as PNG or JPEG (e.g. in an image editor) and try again."
)

# An icon's pictures are at most 256 pixels a side: its directory has a byte
# for each, 0 standing for 256.
_ICON_MAX_SIDE = 256
# The BMP headers whose width Pillow reads as four bytes (the 12-byte OS/2
# header has two). An icon's PNG picture starts with PNG's signature instead.
_BMP_HEADERS = (40, 52, 56, 64, 108, 124)


def _resolve_max_pixels() -> int:
    """Return the configured MAX_IMAGE_PIXELS, honouring env override.

    Env override is documented in ``.env.example`` and
    ``docs/self-hosting.md``. Garbage values fall back to the Pillow-
    compatible default rather than refusing to boot — a self-hoster
    misconfiguring this should still get a working service.
    """
    raw = os.environ.get("FILEMORPH_IMAGE_MAX_MEGAPIXELS", "").strip()
    if not raw:
        return _DEFAULT_MAX_MEGAPIXELS * 1_000_000
    try:
        mp = int(raw)
        if mp < 1 or mp > 10_000:
            raise ValueError
        return mp * 1_000_000
    except ValueError:
        return _DEFAULT_MAX_MEGAPIXELS * 1_000_000


def apply_hardening() -> None:
    """Set MAX_IMAGE_PIXELS + filter DecompressionBombWarning to an error,
    and keep Pillow from starting Ghostscript.

    Idempotent — safe to call multiple times. Re-reads the env var so a
    test can monkeypatch the env between calls and reapply.
    """
    Image.MAX_IMAGE_PIXELS = _resolve_max_pixels()
    # Promote the warning to a synchronously raised error. Pillow's own
    # DecompressionBombError class still fires above the 2× ceiling; this
    # filter closes the warn-but-continue gap below it so EVERY oversize
    # image fails fast and identically.
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    # ``False`` (not ``None``, which means "look it up") is how Pillow
    # records a missing Ghostscript: EPS loading then raises OSError and no
    # process starts. See the module docstring. Not tied to WeasyPrint:
    # keep it after the WeasyPrint 70 upgrade.
    EpsImagePlugin.gs_binary = False


# What an image over the size limit raises, for the routes to answer with
# ``decompression_bomb``: the error above Pillow's 2× ceiling, and below it
# the warning that ``apply_hardening`` turns into an exception. The warning is
# no subclass of the error, so a handler needs both.
DECOMPRESSION_BOMB = (Image.DecompressionBombError, Image.DecompressionBombWarning)


def open_image(fp: str | os.PathLike[str] | IO[bytes]) -> ImageFile.ImageFile:
    """``Image.open`` for uploaded data, limited to ``IMAGE_INPUT_FORMATS``.

    Raises ``InvalidInputError`` with a fixed message when none of these
    readers recognises the file: not an image, too damaged to be recognised,
    or another format.

    The image forgets the file's name. Pillow memory-maps an uncompressed
    image it has a name for instead of reading it, and Pillow 13.0 maps a
    TIFF page turned by a quarter (orientation 5–8) at its turned size, not
    its stored one: the pixels came out scrambled (python-pillow/Pillow#10220,
    fixed after 13.0). Without the name Pillow reads them; the name is used
    for nothing else here (the image itself is never saved), and the file
    stays the image's to close. Keep it after Pillow's fix: a loaded picture
    holds no mapping of the upload's file (#320), and Pillow checks the size
    of every TIFF page it reads — a mapped later page skipped that check.

    Pillow reads the pixels half a row at a time at least (``read_in_rows``)
    — an icon's picture excepted, which it reads while opening the file: an
    icon whose BMP picture is wider than an icon can be gets the same
    ``InvalidInputError`` before Pillow opens it.
    """
    # Pillow imports its plugins lazily; load them all so the filter below
    # sees every reader. A no-op after the first call.
    Image.init()
    # Image.ID lists the registered readers in Pillow's own detection order.
    formats = [fmt for fmt in Image.ID if fmt in IMAGE_INPUT_FORMATS]
    if _wide_icon(fp):
        raise InvalidInputError(_UNREADABLE_IMAGE)
    try:
        img = Image.open(fp, formats=formats)
    except UnidentifiedImageError as exc:
        raise InvalidInputError(_UNREADABLE_IMAGE) from exc
    img.filename = ""
    try:
        read_in_rows(img)
    except BaseException:
        img.close()  # and with it the upload (#320)
        raise
    return img


def read_in_rows(img: ImageFile.ImageFile) -> None:
    """Have Pillow read the uncompressed pixels of ``img`` half a row at a
    time at least. ``open_image`` does it for an upload's first page; after
    seeking to another page, call it again (``strip_pages`` does): pages
    differ.

    Pillow reads uncompressed pixels (a TIFF page, a BMP) in blocks and joins
    them until a row is whole, so a very wide row took many blocks. With
    this hook every read brings at least a row as the file stores it, or the
    widest strip's or tile's width in the bytes a pixel takes in memory
    (one, two or four, as Pillow holds them; at least half of what a TIFF
    stores for one, eight bytes at most), but never more than the file
    holds: a row takes a read or two. Pillow's own block size
    (``decodermaxblock``) does not reach every read.

    A TIFF tile may run past the right edge of its page: its rows in the
    file are as long as it is wide. Rows over 64 KB and more than twice the
    page's are refused, as a damaged file's (``InvalidInputError``); tiles
    are commonly 256 to 1 024 pixels wide.

    The hook reads from the image's file as it is at the time: an AVIF hands
    Pillow its decoded pixels as a file of their own when it loads.
    """
    vars(img).pop("load_read", None)  # one set for another page
    pixel = 1 if img.mode in ("1", "L", "P") else 2 if img.mode.startswith("I;16") else 4
    widths, strides = [], []
    for name, extents, _, args in img.tile:
        if name == "raw":
            left, _, right, _ = extents or (0, 0, img.width, img.height)  # none: all of it
            widths.append((right - left) * pixel)
            # The arguments: the raw mode, then the length of a row in the
            # file where Pillow knows it (a BMP's; a TIFF tile past its page).
            strides.append(args[1] if isinstance(args, tuple) and len(args) > 1 else 0)
    if not widths:
        return
    row, stride = max(widths), max(strides)
    if stride > max(2 * row, ImageFile.MAXBLOCK):
        raise InvalidInputError(_UNREADABLE_IMAGE)
    block = min(max(row, stride), file_size(img))
    image = weakref.ref(img)  # the image holds the hook: no cycle

    def load_read(size: int) -> bytes:  # Pillow's hook for reading pixels
        return image().fp.read(max(size, block))

    img.load_read = load_read


def file_size(img: Image.Image) -> int:
    """The size of the file ``img`` reads from; it goes on reading where it was."""
    fp = img.fp
    here = fp.tell()
    try:
        return fp.seek(0, 2)
    finally:
        fp.seek(here)


def _wide_icon(fp: str | os.PathLike[str] | IO[bytes]) -> bool:
    """Whether ``fp`` is an icon (ICO) with a BMP picture wider than an icon
    can be (``_ICON_MAX_SIDE``). A file is left where it was."""
    if isinstance(fp, (str, os.PathLike)):
        with open(fp, "rb") as f:
            return _wide_icon(f)
    here = fp.tell()
    try:
        head = fp.read(6)
        if head[:4] != b"\0\0\1\0":  # an icon's signature
            return False
        directory = fp.read(16 * int.from_bytes(head[4:6], "little"))
        # Each picture's 16-byte entry ends with where the picture starts; in
        # the order of the file, the reads run forward through it.
        starts = {
            int.from_bytes(directory[end - 4 : end], "little")
            for end in range(16, len(directory) + 1, 16)
        }
        for start in sorted(starts):
            fp.seek(start)
            header = fp.read(8)  # a BMP picture's header size and width
            if (
                int.from_bytes(header[:4], "little") in _BMP_HEADERS
                and int.from_bytes(header[4:8], "little") > _ICON_MAX_SIDE
            ):
                return True
        return False
    finally:
        fp.seek(here)


# Fire once at import so a single ``import app.core.image_hardening``
# anywhere in the startup path is enough. ``app/main.py`` does this
# explicitly to make the dependency obvious.
apply_hardening()
