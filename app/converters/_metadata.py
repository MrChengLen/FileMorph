# SPDX-License-Identifier: AGPL-3.0-or-later
"""NEU-C.2: PII-stripping helper for image saves.

Why this exists in a separate module:

Cameras and image editors embed metadata that often counts as personal
data under GDPR Art. 4 — GPS coordinates, camera serial, capture
timestamps, the photographer's name (XMP/IPTC), even network-connected
camera Wi-Fi SSIDs (MakerNote). FileMorph's privacy posture is "we
don't keep anything", but if we hand back a JPEG with the original
EXIF intact we have just laundered the source's PII through our
service into wherever the user uploads it next.

The strip is **default-on** for every image conversion and
compression. There is no per-request opt-out: a caller who
genuinely needs the metadata kept (forensic-photography pipelines,
some archival workflows) can hold the original — FileMorph's job is
to deliver a clean output. Compliance-edition self-hosters get this
behaviour automatically, with no configuration; the ISO/IEC 27001:2022
A.5.12 ("classification of information") and BSI APP.5.1 ("Allgemeine
Anwendungssoftware") expectations around metadata cleaning are met
by code, not policy.

The implementation pastes the pixel data into a fresh
``Image.new(...)`` so any unread auxiliary chunks Pillow may have
buffered are not carried over either (a photo turned upright first is
already such a fresh image, from ``transpose()``). We *do* keep the ICC colour
profile — dropping it can shift colours visibly on wide-gamut workflows.
It says which colours the pixel values mean. A display profile (a macOS
screenshot's, say) can name the monitor — make, model, and in Apple's
``mmod`` tag its serial number — and carry a profile name its user chose;
never the place or the time a photo was taken.

If a future requirement adds an opt-in to keep metadata, the right
shape is a route-level Form parameter that flows down into the
converter/compressor as ``keep_metadata=True`` — not an env-var
toggle, because a per-deployment "ship metadata sometimes" default
is exactly the kind of footgun a compliance regime exists to
prevent.
"""

from __future__ import annotations

import struct
import time

from PIL import ExifTags, Image

from app.converters.base import InvalidInputError, TiffTooLargeError

# EXIF orientation → the turn that shows the image the way viewers do; the
# table ImageOps.exif_transpose uses.
_UPRIGHT = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}


def _upright(img: Image.Image) -> Image.Image:
    """``img`` turned the way viewers show it.

    Phones store a photo as the sensor saw it and record the turn in the
    EXIF orientation tag (or in XMP); every viewer applies it. Stripping the
    tag without applying it hands back a sideways photo, so the turn goes
    into the pixels first, exactly once: Pillow turns a TIFF while loading
    it and drops the tag (hence the load first), and pillow-heif resets a
    HEIC's orientation to 1 as it opens it, libheif having done the turn.
    Not ``ImageOps.exif_transpose``: it also writes the EXIF block back,
    which we drop anyway, and that write raises on malformed blocks.
    """
    img.load()
    try:
        method = _UPRIGHT.get(img.getexif().get(ExifTags.Base.Orientation))
    except Exception:
        # An unreadable EXIF block (SyntaxError, struct.error, … — it is
        # untrusted input) has no turn to apply; it goes with the rest.
        return img
    return img if method is None else img.transpose(method)


def _transparency_fits(mode: str, value: object) -> bool:
    """Whether ``value`` is a transparency the encoders take for ``mode``: a
    palette index or alpha table, a grey level, or an RGB colour. A stale or
    malformed one — an index or table past 256 entries, a grey level left on
    an image converted to RGB — is dropped, as it always was."""
    if mode == "P":
        return (isinstance(value, int) and 0 <= value < 256) or (
            isinstance(value, bytes) and len(value) <= 256
        )
    if mode in ("1", "L", "I") or mode.startswith("I;16"):
        return isinstance(value, int)
    return mode == "RGB" and isinstance(value, tuple) and len(value) == 3


# The colour space an ICC profile describes (bytes 16-19 of its header) and
# the modes whose pixels it can describe.
_ICC_MODES = {
    b"RGB ": ("RGB", "RGBA", "RGBX", "P", "PA"),
    b"GRAY": ("1", "L", "LA", "I", "F"),
    b"CMYK": ("CMYK",),
    b"Lab ": ("LAB",),
}


# RGB profiles take a few KB (sRGB about 3 KB, Display P3 under 1 KB), print
# profiles up to about 2 MB (ECI's ISO Coated v2). A larger one is no colour
# space worth keeping: Pillow splits it for a JPEG in pure Python, in time
# growing with the square of its size (4 MB: 50 ms per encode, 16 MB: 0.8 s,
# and target-size compression encodes up to twenty times), and past 255
# pieces it writes it broken.
ICC_MAX_BYTES = 1 << 22


def _icc_fits(mode: str, icc: bytes) -> bool:
    """Whether ``icc`` describes pixels of ``mode``. A profile left over from
    a mode conversion — a CMYK profile on pixels converted to RGB, say — would
    make every viewer misread the colours, so it goes."""
    if len(icc) < 20:
        return False
    space = icc[16:20]
    if space == b"GRAY" and mode.startswith("I;16"):
        return True
    return mode in _ICC_MODES.get(space, ())


def icc_for(img: Image.Image, pil_fmt: str) -> bytes | None:
    """The colour profile to pass to the encoder for ``pil_fmt``: the one
    ``strip_metadata`` kept, if it fits the pixels as that format writes them.
    WebP writes colour whatever the mode, AVIF too except for greyscale, so a
    greyscale profile would mislabel them; JPEG writes the mode it is given.
    JPEG and WebP write a profile only when passed one."""
    icc = img.info.get("icc_profile")
    if not icc:
        return None
    written = {"WEBP": "RGB", "AVIF": "L" if img.mode == "L" else "RGB"}.get(pil_fmt, img.mode)
    return icc if _icc_fits(written, icc) else None


def strip_metadata(img: Image.Image) -> Image.Image:
    """Return a copy of ``img`` with EXIF / XMP / IPTC / MakerNote
    stripped, ICC colour profile preserved — turned upright first, since
    the EXIF orientation goes with the rest (see ``_upright``).

    Implementation note: ``Image.new(mode, size)`` + ``paste()``
    constructs a fresh PIL image whose ``info`` dict starts empty; a
    turned image is fresh already (``transpose()``) and gets an empty
    ``info`` instead. Pillow encoders look at ``info`` (and at format-specific keys
    inside it) to decide whether to write back metadata blocks; an
    empty ``info`` therefore yields a metadata-free output regardless
    of which save format the caller picks. Past that turn, the pixel data,
    the mode, and the size are preserved bit-for-bit — for a palette image with
    its palette, since its pixels are only indices into it, and for any
    image with its transparent index or colour where that fits the mode.
    Both are pixel data, not metadata; without the palette every pixel
    comes out one colour.

    The ICC profile is the one piece of metadata we re-attach because
    losing it can desaturate or shift colours on wide-gamut images — it
    describes the *colour space*, not where or when the photo was taken (a
    display profile can name the monitor and a profile name its user chose;
    see the module docstring). Only one that fits the
    mode (``_icc_fits``) and is at most ``ICC_MAX_BYTES``; the callers pass
    it on with ``icc_for`` to the encoders that need it passed.
    """
    turned = _upright(img)
    icc = turned.info.get("icc_profile")
    transparency = turned.info.get("transparency")
    if turned is img:
        clean = Image.new(img.mode, img.size)
        if img.mode in ("P", "PA") and img.palette is not None:
            palette_mode = img.palette.mode
            clean.putpalette(img.getpalette(palette_mode), palette_mode)
        clean.paste(img)
    else:
        # The turn already made a fresh image, palette included: emptying its
        # info strips it the same way, and the pixels sit in memory twice at
        # most (the caller's copy and this one), not three times.
        clean = turned
        clean.info = {}
    if icc and len(icc) <= ICC_MAX_BYTES and _icc_fits(clean.mode, icc):
        clean.info["icc_profile"] = icc
    if transparency is not None and _transparency_fits(clean.mode, transparency):
        clean.info["transparency"] = transparency
    return clean


# Pages of one TIFF at most: a page costs a little time however small it is.
MAX_PAGES = 1000
# Seconds for reading a TIFF's pages. A scanned document takes a few at most
# (ten colour A4 pages at 300 dpi: 0.7 s); a crafted one can make each page's
# header cost a fifth of a second to read (65 000 entries in a 2 MB file),
# which no page or pixel count catches.
PAGES_SECONDS = 15
# The TIFF tag of a page's own colour profile.
_ICC_TAG = 34675
_DAMAGED_PAGE = (
    "A page of this TIFF is damaged and can't be read. Save the file again (for example "
    "in your scanning app or an image editor) and try again."
)


def own_page_profile(img: Image.Image) -> None:
    """Pillow keeps a TIFF page's colour profile in ``info`` for a later page
    that has none; such a page loses it here (call after each seek)."""
    tags = getattr(img, "tag_v2", None)
    if tags is not None and _ICC_TAG not in tags:
        img.info.pop("icc_profile", None)


def strip_pages(img: Image.Image) -> list[Image.Image]:
    """Every page of a multi-page TIFF, each stripped as ``strip_metadata``
    strips one picture.

    The pages are all in memory at once, and Pillow checks only the first
    page's size on opening, so each later page is checked before it is decoded:
    together they may take as many bytes as one colour picture at the size
    limit (``Image.MAX_IMAGE_PIXELS`` at four bytes a pixel), counting
    Pillow's pointer for each row. Pillow keeps a black-and-white or grey
    page at a byte a pixel — a scanned letter of forty A4 pages at 300 dpi
    fits; any other page counts four (a palette page becomes RGB on its way
    to a PDF). Past that, past ``MAX_PAGES`` or past ``PAGES_SECONDS``,
    ``TiffTooLargeError`` names the way out: smaller files.

    Seeking from one page to the next reads only its header. A header that
    can't be read past the end of the file is a scanner's stray pointer to a
    page that isn't there: the file ends, as in libtiff's readers. Anywhere
    else — or a page without width or height, or pixels that can't be read —
    the page is damaged: ``InvalidInputError`` (400), never fewer pages
    without a word or a server error.
    """
    pages: list[Image.Image] = []
    held = 0
    next_page = 0  # where the page before says the next one starts
    deadline = time.monotonic() + PAGES_SECONDS
    while True:
        try:
            img.seek(len(pages))
        except EOFError:
            return pages
        except Exception as exc:
            if next_page >= _file_size(img):
                return pages
            raise InvalidInputError(_DAMAGED_PAGE) from exc
        next_page = getattr(img.tag_v2, "next", 0) if hasattr(img, "tag_v2") else 0
        own_page_profile(img)
        if not img.width or not img.height:
            raise InvalidInputError(_DAMAGED_PAGE)
        size = 1 if img.mode in ("1", "L") else 4
        held += (img.width * size + 8) * img.height  # 8: Pillow's pointer to each row
        limit = 4 * Image.MAX_IMAGE_PIXELS if Image.MAX_IMAGE_PIXELS else None
        # The first page's size Pillow checked on opening, as for any image.
        too_much = bool(pages) and limit is not None and held > limit
        if len(pages) == MAX_PAGES or too_much or time.monotonic() > deadline:
            raise TiffTooLargeError()
        try:
            pages.append(strip_metadata(img))
        except (OSError, SyntaxError, ValueError, TypeError, struct.error) as exc:
            raise InvalidInputError(_DAMAGED_PAGE) from exc


def _file_size(img: Image.Image) -> int:
    fp = img.fp
    here = fp.tell()
    try:
        return fp.seek(0, 2)
    finally:
        fp.seek(here)
