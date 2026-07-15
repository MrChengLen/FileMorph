# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path

from PIL import Image

from app.converters._metadata import strip_metadata
from app.converters.base import BaseConverter
from app.converters.registry import register

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


def _open_image(path: Path) -> Image.Image:
    img = Image.open(path)
    # Ensure we have a usable mode for saving
    if img.mode in ("RGBA", "LA", "P"):
        return img
    return img.convert("RGB") if img.mode != "RGB" else img


class _ImageConverter(BaseConverter):
    """Generic image-to-image converter via Pillow."""

    def __init__(self, tgt_fmt: str, quality: int = 85):
        self._tgt_fmt = tgt_fmt
        self._default_quality = quality

    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        quality = int(kwargs.get("quality", self._default_quality))
        img = _open_image(input_path)

        pil_fmt = _PIL_FORMAT.get(self._tgt_fmt, self._tgt_fmt.upper())

        # NEU-C.2: strip PII-bearing metadata (EXIF GPS / camera serial /
        # XMP creator / IPTC byline) before any save path. Default-on
        # for every image conversion — see app/converters/_metadata.py.
        # JPEG requires RGB (no alpha); do the mode coercion before the
        # strip so we don't paste from a soon-to-be-discarded mode.
        if pil_fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        img = strip_metadata(img)

        # PNG and BMP are lossless — quality param is ignored
        if pil_fmt == "PNG":
            # compress_level=9 = maximum zlib deflate effort; optimize=True
            # runs an extra pass for smaller filter/palette choices. Together
            # they shave 20-40 % off the default PNG encoder output.
            img.save(output_path, format="PNG", optimize=True, compress_level=9)
        elif pil_fmt in ("BMP", "GIF", "ICO", "TIFF"):
            img.save(output_path, format=pil_fmt)
        else:
            img.save(output_path, format=pil_fmt, quality=quality, optimize=True)

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
# Image → PDF  (each image becomes a single-page PDF)
# ---------------------------------------------------------------------------
# Asymmetric (many image formats → one PDF target), so it can't ride the
# image↔image loop above. Pillow writes PDF natively, but the PDF encoder has
# no alpha channel — flatten RGBA/LA/P onto white first (same spirit as the
# JPEG path), then strip metadata like every other image conversion.
class _ImageToPdfConverter(BaseConverter):
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        img = _open_image(input_path)
        if img.mode in ("RGBA", "LA", "P"):
            rgba = img.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img = strip_metadata(img)
        # resolution=150 DPI controls the physical page size Pillow assigns the
        # single image page — a sensible default for typical phone photos/scans.
        img.save(output_path, format="PDF", resolution=150.0)
        return output_path


# Register image→pdf for every supported image source (heic/heif only when
# pillow-heif is installed — _IMAGE_FORMATS already encodes that). One class
# serves all pairs since the target is always PDF (no per-target closure).
for _src in _IMAGE_FORMATS:
    register((_src, "pdf"))(_ImageToPdfConverter)
