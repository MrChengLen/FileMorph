# SPDX-License-Identifier: AGPL-3.0-or-later
from contextlib import closing
from pathlib import Path

from PIL import Image

from app.compressors.image import save_tiff
from app.converters._metadata import icc_for, own_page_profile, strip_metadata, strip_pages
from app.converters.base import BaseConverter
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
                if src.format == "TIFF" and _several_pages(src):
                    # A picture format holds one page: the first. PDF holds them all.
                    self.warnings.append("pages=first")
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

        # PNG and BMP are lossless — quality param is ignored
        if pil_fmt == "PNG":
            # compress_level=9 = maximum zlib deflate effort; optimize=True
            # runs an extra pass for smaller filter/palette choices. Together
            # they shave 20-40 % off the default PNG encoder output.
            img.save(output_path, format="PNG", optimize=True, compress_level=9)
        elif pil_fmt in ("BMP", "GIF", "ICO", "TIFF"):
            img.save(output_path, format=pil_fmt)
        else:
            # JPEG, WebP, AVIF. JPEG and WebP write the colour profile that
            # strip_metadata kept only when passed it; without it an iPhone
            # photo (Display P3) turns dull.
            icc = icc_for(img, pil_fmt)
            img.save(output_path, format=pil_fmt, quality=quality, optimize=True, icc_profile=icc)

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
class _ImageToPdfConverter(BaseConverter):
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        # Closed however the block ends (see _ImageConverter.convert).
        with closing(open_image(input_path)) as src:
            if src.format == "TIFF":
                pages = [_pdf_page(page) for page in strip_pages(src)]
            else:
                pages = [_pdf_page(strip_metadata(_usable(src)))]
        # resolution=150 DPI controls the physical page size Pillow assigns
        # each image page — a sensible default for typical phone photos/scans.
        pages[0].save(
            output_path, format="PDF", resolution=150.0, save_all=True, append_images=pages[1:]
        )
        return output_path


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
