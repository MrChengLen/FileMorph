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
buffered are not carried over either. We *do* keep the ICC colour
profile — it is not PII, and dropping it can shift colours visibly
on wide-gamut workflows.

If a future requirement adds an opt-in to keep metadata, the right
shape is a route-level Form parameter that flows down into the
converter/compressor as ``keep_metadata=True`` — not an env-var
toggle, because a per-deployment "ship metadata sometimes" default
is exactly the kind of footgun a compliance regime exists to
prevent.
"""

from __future__ import annotations

from PIL import Image


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


def strip_metadata(img: Image.Image) -> Image.Image:
    """Return a copy of ``img`` with EXIF / XMP / IPTC / MakerNote
    stripped, ICC colour profile preserved.

    Implementation note: ``Image.new(mode, size)`` + ``paste()``
    constructs a fresh PIL image whose ``info`` dict starts empty.
    Pillow encoders look at ``info`` (and at format-specific keys
    inside it) to decide whether to write back metadata blocks; an
    empty ``info`` therefore yields a metadata-free output regardless
    of which save format the caller picks. The pixel data, the mode,
    and the size are preserved bit-for-bit — for a palette image with
    its palette, since its pixels are only indices into it, and for any
    image with its transparent index or colour where that fits the mode.
    Both are pixel data, not metadata; without the palette every pixel
    comes out one colour.

    The ICC profile is the one piece of metadata we re-attach because
    losing it can desaturate or shift colours on wide-gamut images
    and is not PII — it describes the *colour space*, not who took
    the photo or where.
    """
    icc = img.info.get("icc_profile")
    transparency = img.info.get("transparency")
    clean = Image.new(img.mode, img.size)
    if img.mode in ("P", "PA") and img.palette is not None:
        palette_mode = img.palette.mode
        clean.putpalette(img.getpalette(palette_mode), palette_mode)
    clean.paste(img)
    if icc:
        clean.info["icc_profile"] = icc
    if transparency is not None and _transparency_fits(img.mode, transparency):
        clean.info["transparency"] = transparency
    return clean
