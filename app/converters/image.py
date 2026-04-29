from pathlib import Path

from PIL import Image

from app.converters.base import BaseConverter
from app.converters.registry import register

# Register pillow-heif if available
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    _heif_available = True
except ImportError:
    _heif_available = False

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

        # PNG and BMP are lossless — quality param is ignored
        if pil_fmt == "PNG":
            # compress_level=9 = maximum zlib deflate effort; optimize=True
            # runs an extra pass for smaller filter/palette choices. Together
            # they shave 20-40 % off the default PNG encoder output.
            img.save(output_path, format="PNG", optimize=True, compress_level=9)
        elif pil_fmt in ("BMP", "GIF", "ICO", "TIFF"):
            img.save(output_path, format=pil_fmt)
        else:
            # JPEG requires RGB (no alpha)
            if pil_fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")
            img.save(output_path, format=pil_fmt, quality=quality, optimize=True)

        return output_path


# Dynamically register all image↔image combinations
_sources = _IMAGE_FORMATS
_targets = list(_PIL_FORMAT.keys())  # heic/heif output not supported by Pillow

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
