# SPDX-License-Identifier: AGPL-3.0-or-later
from contextlib import closing
from pathlib import Path

from PIL import Image
from pypdf import PdfWriter, Transformation, apply_configuration, get_configuration

from app.compressors.image import save_tiff
from app.converters._metadata import (
    _DPI_RANGE,
    dpi_for,
    icc_for,
    load_upright,
    own_page_profile,
    strip_metadata,
    strip_pages,
)
from app.converters.base import BaseConverter, OutputTooLargeError
from app.converters.registry import register
from app.core.image_hardening import open_image

# Register pillow-heif if available
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    _heif_available = True
except ImportError:
    _heif_available = False

# Register pillow-avif-plugin if available. Unlike pillow-heif, the import
# itself registers AVIF with Pillow (open + save) — there is no explicit
# opener call. Both directions (encode + decode) become available.
try:
    import pillow_avif  # noqa: F401

    _avif_available = True
except ImportError:
    _avif_available = False

# PIL format identifiers per extension
_PIL_FORMAT = {
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

# AVIF is both readable and writable via pillow-avif-plugin, so — unlike the
# read-only heic/heif inputs below — it belongs in _PIL_FORMAT and therefore
# in both the source and target sets the registration loop derives from it.
if _avif_available:
    _PIL_FORMAT["avif"] = "AVIF"

_IMAGE_FORMATS = list(_PIL_FORMAT.keys())
if _heif_available:
    _IMAGE_FORMATS = ["heic", "heif"] + _IMAGE_FORMATS


def _usable(img: Image.Image) -> Image.Image:
    # Ensure we have a usable mode for saving
    if img.mode in ("RGBA", "LA", "P"):
        return img
    return img.convert("RGB") if img.mode != "RGB" else img


def _several_pages(img: Image.Image) -> bool:
    """Whether a TIFF has a second page; seeking to it reads only its header.
    One that can't be read counts as none: the first page converts as before."""
    try:
        img.seek(1)
    except Exception:
        several = False
    else:
        several = True
    img.seek(0)
    own_page_profile(img)  # not the second page's
    return several


class _ImageConverter(BaseConverter):
    """Generic image-to-image converter via Pillow."""

    def __init__(self, tgt_fmt: str, quality: int = 85):
        self._tgt_fmt = tgt_fmt
        self._default_quality = quality
        # X-FileMorph-Warnings tokens (convert.py reads them after convert).
        self.warnings: list[str] = []

    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        quality = int(kwargs.get("quality", self._default_quality))
        pil_fmt = _PIL_FORMAT.get(self._tgt_fmt, self._tgt_fmt.upper())

        # The upload is closed however the block ends: an exception would
        # otherwise hold its file open until the request is over, and Windows
        # cannot delete an open file. Closing the image, not just leaving
        # ``with`` on it, also releases a file Pillow mapped into memory
        # instead of reading (an uncompressed BMP). What leaves the block are
        # copies in memory: the saves below need no open file.
        pages: list[Image.Image] | None = None
        with closing(open_image(input_path)) as src:
            if src.format == "TIFF" and pil_fmt == "TIFF":
                # TIF ↔ TIFF: the target holds every page — packed as compressing does.
                pages = strip_pages(src)
            else:
                if src.format == "TIFF":
                    if _several_pages(src):
                        # A picture format holds one page: the first. PDF holds them all.
                        self.warnings.append("pages=first")
                    # Pillow turns the page as it loads it; load_upright turns
                    # its resolution along — before _usable converts it.
                    load_upright(src)
                img = _usable(src)
                # NEU-C.2: strip PII-bearing metadata (EXIF GPS / camera serial /
                # XMP creator / IPTC byline) before any save path. Default-on
                # for every image conversion — see app/converters/_metadata.py.
                # JPEG requires RGB (no alpha); do the mode coercion before the
                # strip so we don't paste from a soon-to-be-discarded mode.
                if pil_fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
                    img = img.convert("RGB")
                elif (
                    pil_fmt == "GIF"
                    and isinstance(img.info.get("transparency"), bytes)
                    and len(img.info["transparency"]) <= 256
                ):
                    # GIF has one transparent index, not a PNG's alpha table. (A
                    # longer, malformed table is dropped by strip_metadata instead.)
                    img = img.convert("RGBA")
                img = strip_metadata(img)
        if pages is not None:
            save_tiff(pages, output_path)
            return output_path

        # PNG and BMP are lossless — quality param is ignored. The resolution
        # goes where the format has a place for it (dpi_for).
        dpi = dpi_for(img, pil_fmt)
        if pil_fmt == "PNG":
            # compress_level=9 = maximum zlib deflate effort; optimize=True
            # runs an extra pass for smaller filter/palette choices. Together
            # they shave 20-40 % off the default PNG encoder output.
            img.save(output_path, format="PNG", optimize=True, compress_level=9, **dpi)
        elif pil_fmt in ("BMP", "GIF", "ICO", "TIFF"):
            img.save(output_path, format=pil_fmt, **dpi)
        else:
            # JPEG, WebP, AVIF. JPEG and WebP write the colour profile that
            # strip_metadata kept only when passed it; without it an iPhone
            # photo (Display P3) turns dull.
            icc = icc_for(img, pil_fmt)
            img.save(
                output_path,
                format=pil_fmt,
                quality=quality,
                optimize=True,
                icc_profile=icc,
                **dpi,
            )

        return output_path


# Dynamically register all image↔image combinations. _targets is derived from
# _PIL_FORMAT, which holds every format Pillow can *write* here: heic/heif are
# read-only inputs (in _IMAGE_FORMATS but not _PIL_FORMAT), whereas avif is both
# readable and writable, so it is in both sets and gets *→avif and avif→* pairs.
_sources = _IMAGE_FORMATS
_targets = list(_PIL_FORMAT.keys())

for _src in _sources:
    for _tgt in _targets:
        if _src == _tgt or (_src in ("jpeg",) and _tgt == "jpg"):
            continue

        # Build the pair and register a dedicated class instance via a closure
        def _make_converter(tgt: str) -> type[BaseConverter]:
            class _Converter(_ImageConverter):
                def __init__(self):
                    super().__init__(tgt)

            _Converter.__name__ = f"ImageTo{tgt.upper()}Converter"
            return _Converter

        _cls = _make_converter(_tgt)
        register((_src, _tgt))(_cls)


# ---------------------------------------------------------------------------
# Image → PDF  (an image becomes a page, a multi-page TIFF a page each)
# ---------------------------------------------------------------------------
# Asymmetric (many image formats → one PDF target), so it can't ride the
# image↔image loop above. Strip metadata first like every other image
# conversion — that also turns a photo upright, from the EXIF the flattening
# below drops.
#
# The resolution sets the page size: a picture becomes a page at 150 dpi — a
# photo's 72 dpi is a camera's default, not a size. A TIFF page has its own
# where it has one (strip_metadata keeps it): a scanner or fax machine
# records the one it scanned at, so a fax in normal mode (204 × 98 dpi, its
# pixels twice as tall as wide) is the letter it was, not a squat page.
_PDF_DPI = (150.0, 150.0)
# Acrobat shows a page of at most 200 inches a side (14 400 points, ISO
# 32000-1 Annex C); Pillow writes no UserUnit to go past that.
_PDF_MAX_INCHES = 200


class _ImageToPdfConverter(BaseConverter):
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        # Closed however the block ends (see _ImageConverter.convert).
        with closing(open_image(input_path)) as src:
            if src.format == "TIFF":
                pages = strip_pages(src)
                dpis = [_page_dpi(page, page.info.get("dpi", _PDF_DPI)) for page in pages]
                pages = [_pdf_page(page) for page in pages]
            else:
                page = _pdf_page(strip_metadata(_usable(src)))
                pages, dpis = [page], [_page_dpi(page, _PDF_DPI)]
        pages[0].save(
            output_path, format="PDF", dpi=dpis[0], save_all=True, append_images=pages[1:]
        )
        # Written: the pixels go now. Pillow's writer gave each page a
        # reference to the list of them, which would keep them all alive.
        for page in pages:
            page.close()
        if len(set(dpis)) > 1:
            limit = kwargs.get("max_output_bytes")
            if limit is not None and output_path.stat().st_size > limit:
                raise OutputTooLargeError  # no resizing for a file that is refused anyway
            _size_pages(output_path, dpis)
        return output_path


def _page_dpi(img: Image.Image, dpi: tuple[float, float]) -> tuple[float, float]:
    """``dpi``, raised where the page would be larger than ``_PDF_MAX_INCHES``
    — across and down alike, so it keeps its proportions — but to no more
    than a measured resolution (``_DPI_RANGE``): past that, a side of a
    crafted page gets too thin for Pillow to write as a plain number."""
    x, y = dpi
    over = max(img.width / x, img.height / y) / _PDF_MAX_INCHES
    over = min(over, _DPI_RANGE[1] / max(x, y))
    return (x * over, y * over) if over > 1 else dpi


def _size_pages(path: Path, dpis: list[tuple[float, float]]) -> None:
    """Pillow's PDF writer sizes every page by the first page's resolution; a
    page with another one — a fax can mix normal and fine pages — is scaled
    to its own size here, its image with it. Not with ``page.scale()``: that
    also writes crop, bleed, trim and art boxes, which inserting the page
    into a PDF (``_fit_image_page``) would leave at this size. The PDF is the
    one Pillow just wrote, so pypdf's limit on a stream's declared length —
    against crafted files — gives way to its size."""
    longest = max(get_configuration().maximum_declared_stream_length, path.stat().st_size)
    with apply_configuration(maximum_declared_stream_length=longest):
        writer = PdfWriter(clone_from=path)
        first_x, first_y = dpis[0]
        for page, (x, y) in zip(writer.pages, dpis, strict=True):
            if (x, y) != (first_x, first_y):
                sx, sy = first_x / x, first_y / y
                page.add_transformation(Transformation().scale(sx, sy))
                page.mediabox = page.mediabox.scale(sx, sy)
        writer.write(path)


def _pdf_page(img: Image.Image) -> Image.Image:
    """A page as Pillow's PDF encoder takes it. It has no alpha channel:
    transparency goes onto white (same spirit as the JPEG path). A TIFF page
    in black and white or grey stays so — as RGB, a scanned letter's page
    takes ten times the bytes."""
    if img.mode in ("RGBA", "LA", "P", "PA"):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    return img if img.mode in ("1", "L", "RGB") else img.convert("RGB")


# Register image→pdf for every supported image source (heic/heif only when
# pillow-heif is installed — _IMAGE_FORMATS already encodes that). One class
# serves all pairs since the target is always PDF (no per-target closure).
for _src in _IMAGE_FORMATS:
    register((_src, "pdf"))(_ImageToPdfConverter)
