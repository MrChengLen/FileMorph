# SPDX-License-Identifier: AGPL-3.0-or-later
"""The original file without its metadata, not re-encoded.

When compressing would not make a file smaller — a photo from the web or a
messenger, already compressed harder than the chosen quality — the
compressor hands back the original instead of a larger re-encode. The
original still carries what ``strip_metadata`` promises to remove (EXIF with
GPS position and camera, XMP and IPTC with names, comments), so the file is
put together anew from the parts that make up the picture: the image data is
copied as it is, the few parts that say how to read it are rebuilt from what
a reader takes from them, everything else is left out. The decoded picture
is checked to be unchanged before the file is used.

What stays: the colour profile the re-encode would keep (``strip_metadata``:
one that fits the pixels, at most ``ICC_MAX_BYTES``), written anew; a JPEG's
JFIF and Adobe segments at the 14 and 12 bytes libjpeg reads of them (no
thumbnail); PNG chunks for transparency, gamma, colour space and pixel size,
at the one length readers read; a JPEG photo's orientation, as a minimal EXIF
block holding only that tag. Data after a JPEG's end (a phone's second
picture or gain map) goes too.

Not caught: bytes hidden inside the coded image data itself — a JPEG's scans
and its tables (up to ``_MAX_TABLE_BYTES``, many times what a photo needs), a
WebP's bitstream. No camera or editor writes metadata there, and finding them
means decoding the bitstream. A PNG's pixel stream is checked to hold exactly
its rows.

``None`` — the caller keeps its re-encode — whenever the file is not plainly
one JPEG, PNG or WebP picture (an animated PNG or WebP: the re-encode keeps
only its first frame anyway), a PNG or WebP is marked as turned (dropping the
mark would turn the picture), a part is unknown, repeated or longer than
readers read, or the file has far more parts than a photo (``_MAX_PARTS``).
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import zlib

from PIL import Image

from app.converters._metadata import ICC_MAX_BYTES, icc_for

logger = logging.getLogger(__name__)

# The formats there is a strip for.
STRIPPABLE = ("JPEG", "PNG", "WEBP")

_ORIENTATION = 0x0112
# Pixels hashed at a time while comparing: one decoded picture in memory.
_HASH_PIXELS = 1 << 20

# JPEG segments of the picture itself: frame headers (SOFn), Huffman and
# arithmetic-coding tables, quantization tables, the restart interval, scans.
_JPEG_PICTURE = {
    0xC0, 0xC1, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB, 0xCC, 0xCD, 0xCE, 0xCF, 0xDA, 0xDB, 0xDD,
}  # fmt: skip
# A scan's coded data runs to the next marker: an 0xFF that is neither a
# stuffed zero nor a restart marker.
_NEXT_MARKER = re.compile(rb"\xff(?![\x00\xd0-\xd7])")
# Profile bytes per APP2 segment, as Pillow splits a profile.
_ICC_PIECE = 65519
# A photo has a few dozen JPEG segments or WebP chunks, a progressive one up
# to a few hundred, and under 10 KB of headers and tables; walking more parts
# in Python would cost more time than decoding the picture.
_MAX_PARTS = 4096
_MAX_TABLE_BYTES = 1 << 16

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_PICTURE = {b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"}
# PNG chunks for how the picture looks, at the one length they have.
_PNG_LOOKS = {b"gAMA": 4, b"cHRM": 32, b"sRGB": 1, b"pHYs": 9, b"cICP": 4, b"mDCv": 24, b"cLLi": 8}
_PNG_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
# Adam7: each pass's first column and row and its steps.
_ADAM7 = (
    (0, 0, 8, 8),
    (4, 0, 8, 8),
    (0, 4, 4, 8),
    (2, 0, 4, 4),
    (0, 2, 2, 4),
    (1, 0, 2, 2),
    (0, 1, 1, 2),
)
_INFLATE_STEP = 1 << 14

# WebP VP8X flags that stay: alpha, and the colour profile while there is one.
_VP8X_ALPHA, _VP8X_ICC = 0x10, 0x20


def original_without_metadata(data: bytes, pil_fmt: str) -> bytes | None:
    """``data`` (a ``pil_fmt`` file) without its metadata, or ``None``."""
    if pil_fmt not in STRIPPABLE:
        return None
    try:
        with Image.open(io.BytesIO(data), formats=[pil_fmt]) as img:
            if not _plain(img, pil_fmt):
                return None
            orientation, icc = _orientation(img), _profile(img, pil_fmt)
            if pil_fmt == "JPEG":
                stripped = _strip_jpeg(data, orientation, icc)
            elif orientation == 1:
                stripped = (_strip_png if pil_fmt == "PNG" else _strip_webp)(data, icc)
            else:
                return None
            if stripped is None:
                return None
            before = _picture(img)
        # One decoded picture at a time: the first is closed, its pixels gone.
        with Image.open(io.BytesIO(stripped), formats=[pil_fmt]) as img:
            same = (
                _plain(img, pil_fmt)
                and (_orientation(img), _profile(img, pil_fmt)) == (orientation, icc)
                and _picture(img) == before
            )
    except Exception as exc:
        # Untrusted input this reader doesn't follow: the re-encode stays.
        logger.info("Original not stripped (%s)", type(exc).__name__)
        return None
    return stripped if same else None


def _plain(img: Image.Image, pil_fmt: str) -> bool:
    """One picture of the format. A JPEG holding more (MPO: a phone's depth
    map or second view) counts as its first; the rest is left out."""
    if pil_fmt == "JPEG":
        return img.format in ("JPEG", "MPO")
    return img.format == pil_fmt and getattr(img, "n_frames", 1) == 1


def _orientation(img: Image.Image) -> int:
    try:
        value = img.getexif().get(_ORIENTATION, 1)
        return value if isinstance(value, int) and 1 <= value <= 8 else 1
    except Exception:
        return 1


def _profile(img: Image.Image, pil_fmt: str) -> bytes | None:
    """The colour profile the re-encode would keep (``strip_metadata``)."""
    icc = icc_for(img, pil_fmt)
    return icc if icc and len(icc) <= ICC_MAX_BYTES else None


def _picture(img: Image.Image) -> tuple:
    """The first frame's mode, size, palette, transparency and a digest of its
    pixels, hashed a strip at a time — never a second copy of them all."""
    img.load()
    width, height = img.size
    rows = max(1, _HASH_PIXELS // max(1, width))
    digest = hashlib.sha256()
    for top in range(0, height, rows):
        digest.update(img.crop((0, top, width, min(height, top + rows))).tobytes())
    palette = img.getpalette() if img.mode in ("P", "PA") else None
    return img.mode, img.size, palette, img.info.get("transparency"), digest.digest()


def _strip_jpeg(data: bytes, orientation: int, icc: bytes | None) -> bytes | None:
    """The picture's own segments and scans as they are, behind JFIF and
    Adobe as libjpeg reads them, the orientation and the colour profile."""
    if data[:2] != b"\xff\xd8":
        return None
    view = memoryview(data)
    jfif = adobe = b""
    picture: list = []
    parts = tables = 0
    pos, end = 2, len(data)
    while pos + 2 <= end:
        parts += 1
        if data[pos] != 0xFF or parts > _MAX_PARTS:
            return None
        marker = data[pos + 1]
        if marker == 0xFF:  # a fill byte
            pos += 1
            continue
        if marker == 0xD9:  # the end: what follows (a second picture) goes
            return _jpeg(jfif, orientation, adobe, icc, picture)
        if pos + 4 > end:
            return None
        segment_end = pos + 2 + int.from_bytes(data[pos + 2 : pos + 4], "big")
        if segment_end < pos + 4 or segment_end > end:
            return None
        head = data[pos + 4 : min(segment_end, pos + 18)]  # all libjpeg reads of APP0/APP14
        if marker == 0xE0 and head.startswith(b"JFIF\x00") and len(head) >= 14:
            jfif = head[:12] + b"\x00\x00"  # no thumbnail
        elif marker == 0xEE and head.startswith(b"Adobe") and len(head) >= 12:
            adobe = head[:12]
        elif marker in _JPEG_PICTURE:
            picture.append(view[pos:segment_end])
            tables += segment_end - pos
            if tables > _MAX_TABLE_BYTES:
                return None  # tables no picture needs: they could carry anything
            if marker == 0xDA:  # a scan: its coded data runs to the next marker
                found = _NEXT_MARKER.search(data, segment_end)
                scan_end = found.start() if found else end
                picture.append(view[segment_end:scan_end])
                segment_end = scan_end
        elif not (0xE0 <= marker <= 0xEF or marker == 0xFE):
            return None  # DNL, hierarchical, reserved or a stray restart marker
        pos = segment_end  # APPn and comments go: EXIF, XMP, MPF, IPTC, Photoshop…
    return None  # no end marker


def _jpeg(jfif: bytes, orientation: int, adobe: bytes, icc: bytes | None, picture: list) -> bytes:
    parts = [b"\xff\xd8"]
    if jfif:
        parts.append(_jpeg_segment(0xE0, jfif))
    if orientation != 1:
        exif = Image.Exif()
        exif[_ORIENTATION] = orientation
        parts.append(_jpeg_segment(0xE1, exif.tobytes()))  # b"Exif\0\0" + the TIFF block
    if adobe:
        parts.append(_jpeg_segment(0xEE, adobe))
    if icc:
        starts = range(0, len(icc), _ICC_PIECE)
        for number, start in enumerate(starts, 1):
            piece = icc[start : start + _ICC_PIECE]
            marker = b"ICC_PROFILE\x00" + bytes((number, len(starts)))
            parts.append(_jpeg_segment(0xE2, marker + piece))
    return b"".join([*parts, *picture, b"\xff\xd9"])


def _jpeg_segment(marker: int, body: bytes) -> bytes:
    return bytes((0xFF, marker)) + (len(body) + 2).to_bytes(2, "big") + body


def _strip_png(data: bytes, icc: bytes | None) -> bytes | None:
    """Header, palette, transparency, pixel stream and end as they are, the
    chunks for how the picture looks, and the colour profile written anew
    (its name is text the user chose) — each once, with a fresh CRC (the old
    one could carry four bytes of anything)."""
    if not data.startswith(_PNG_SIGNATURE):
        return None
    view = memoryview(data)
    out: list = [_PNG_SIGNATURE]
    idat: list = []
    seen: set = set()
    header, entries = b"", 0
    pos = len(_PNG_SIGNATURE)
    while pos + 12 <= len(data):
        length = int.from_bytes(data[pos : pos + 4], "big")
        kind = data[pos + 4 : pos + 8]
        chunk_end = pos + 12 + length
        if chunk_end > len(data) or kind in seen:
            return None
        body = view[pos + 8 : pos + 8 + length]
        if kind == b"iCCP":
            seen.add(kind)
            if icc:
                out += _png_chunk(b"iCCP", b"ICC Profile\x00\x00" + zlib.compress(icc, 9))
        elif kind == b"PLTE" and header[9:10] != b"\x03":
            seen.add(kind)  # a truecolour picture's suggested palette: nothing draws with it
        elif kind in _PNG_PICTURE or kind in _PNG_LOOKS:
            if not _png_length_fits(kind, length, header, entries):
                return None
            if kind == b"IHDR":
                header = bytes(body)
            elif kind == b"PLTE":
                entries = length // 3
            if kind == b"IDAT":
                idat.append(body)
            else:
                seen.add(kind)  # the pixel stream may come in many chunks, the rest once
            out += _png_chunk(kind, body)
            if kind == b"IEND":
                return b"".join(out) if _rows_exact(header, idat) else None
        elif kind[:1].isupper():
            return None  # an unknown critical chunk is not ours to judge
        pos = chunk_end  # text, time, EXIF, animation and any other chunk go
    return None  # no end chunk


def _png_length_fits(kind: bytes, length: int, header: bytes, entries: int) -> bool:
    """A kept chunk holds what readers read of it, nothing more."""
    if kind == b"IHDR":
        return length == 13 and not header
    if not header:
        return False  # everything else comes after the header
    if kind == b"IDAT":
        return True
    if kind == b"IEND":
        return length == 0
    if kind == b"PLTE":
        return 0 < length <= 768 and length % 3 == 0
    if kind == b"tRNS":  # an alpha per palette entry, or the one transparent grey or colour
        colour = header[9]
        return 0 < length <= entries if colour == 3 else length == {0: 2, 2: 6}.get(colour)
    return length == _PNG_LOOKS[kind]


def _rows_exact(header: bytes, idat: list) -> bool:
    """The pixel stream holds exactly the rows the header asks for: nothing
    past the last row, nothing after the end of the zlib stream."""
    width, height = int.from_bytes(header[:4], "big"), int.from_bytes(header[4:8], "big")
    bits = header[8] * _PNG_CHANNELS[header[9]]
    expected = 0
    for left, top, step_x, step_y in _ADAM7 if header[12] else ((0, 0, 1, 1),):
        columns = (width - left + step_x - 1) // step_x
        rows = (height - top + step_y - 1) // step_y
        if columns > 0 and rows > 0:
            expected += rows * (1 + (columns * bits + 7) // 8)  # a filter byte per row
    inflate = zlib.decompressobj()
    total = 0
    for part in idat:
        for start in range(0, len(part), _INFLATE_STEP):
            total += len(inflate.decompress(part[start : start + _INFLATE_STEP]))
            if total > expected:
                return False
    total += len(inflate.flush())
    return inflate.eof and not inflate.unused_data and total == expected


def _png_chunk(kind: bytes, body) -> tuple:
    crc = zlib.crc32(body, zlib.crc32(kind)).to_bytes(4, "big")
    return len(body).to_bytes(4, "big"), kind, body, crc


def _strip_webp(data: bytes, icc: bytes | None) -> bytes | None:
    """The bitstream and its alpha as they are, behind a VP8X header that
    announces only those and the colour profile, written anew."""
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    end = 8 + int.from_bytes(data[4:8], "little")  # what follows the RIFF end goes
    if end > len(data):
        return None
    view = memoryview(data)
    chunks: list = [b"WEBP"]
    seen: set = set()
    parts, pos = 0, 12
    while pos + 8 <= end:
        parts += 1
        kind = data[pos : pos + 4]
        size = int.from_bytes(data[pos + 4 : pos + 8], "little")
        chunk_end = pos + 8 + size + (size & 1)
        if chunk_end > end or parts > _MAX_PARTS or kind in seen:
            return None
        if kind in (b"VP8 ", b"VP8L", b"ALPH"):
            seen.add(kind)
            chunks += _riff_chunk(kind, view[pos + 8 : pos + 8 + size])
        elif kind == b"VP8X":
            seen.add(kind)
            if size != 10:
                return None
            flags = data[pos + 8] & (_VP8X_ALPHA | (_VP8X_ICC if icc else 0))
            chunks += _riff_chunk(kind, bytes((flags, 0, 0, 0)) + data[pos + 12 : pos + 18])
        elif kind == b"ICCP":
            seen.add(kind)
            if icc:
                chunks += _riff_chunk(kind, icc)
        elif kind in (b"ANIM", b"ANMF"):
            return None  # an animation, if of one frame: the re-encode stays
        pos = chunk_end  # EXIF, XMP and any other chunk go
    body = b"".join(chunks)
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def _riff_chunk(kind: bytes, body) -> tuple:
    """A chunk with a zero pad byte to an even size (the old pad could be anything)."""
    return kind, len(body).to_bytes(4, "little"), body, b"\x00" * (len(body) & 1)
