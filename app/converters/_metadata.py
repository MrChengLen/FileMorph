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
behaviour automatically, with no configuration; the ISO 27001 A.8.2
("classification of information") and BSI APP.5.1 ("Allgemeine
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


def strip_metadata(img: Image.Image) -> Image.Image:
    """Return a copy of ``img`` with EXIF / XMP / IPTC / MakerNote
    stripped, ICC colour profile preserved.

    Implementation note: ``Image.new(mode, size)`` + ``paste()``
    constructs a fresh PIL image whose ``info`` dict starts empty.
    Pillow encoders look at ``info`` (and at format-specific keys
    inside it) to decide whether to write back metadata blocks; an
    empty ``info`` therefore yields a metadata-free output regardless
    of which save format the caller picks. The pixel data, the mode,
    and the size are preserved bit-for-bit.

    The ICC profile is the one piece of metadata we re-attach because
    losing it can desaturate or shift colours on wide-gamut images
    and is not PII — it describes the *colour space*, not who took
    the photo or where.
    """
    icc = img.info.get("icc_profile")
    clean = Image.new(img.mode, img.size)
    clean.paste(img)
    if icc:
        clean.info["icc_profile"] = icc
    return clean
