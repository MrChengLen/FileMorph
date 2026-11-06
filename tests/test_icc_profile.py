# SPDX-License-Identifier: AGPL-3.0-or-later
"""The colour profile (ICC) survives compression and conversion.

``strip_metadata`` keeps the profile — it describes the colour space, not who
took the photo — but JPEG and WebP write it only when passed ``icc_profile``.
Without it a wide-gamut photo (an iPhone's Display P3, Adobe RGB) is read as
sRGB and its colours turn dull. A profile that no longer fits the pixels (a
CMYK one after the conversion to RGB) goes instead of being misapplied.
"""

from pathlib import Path

import pytest
from PIL import Image, ImageCms

from app.compressors.image import compress_image, compress_image_to_target
from app.converters._metadata import ICC_MAX_BYTES, _icc_fits, icc_for, strip_metadata
from app.converters.registry import get_converter, get_supported_conversions

SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def _stand_in(space: bytes, size: int = 600) -> bytes:
    """A profile-shaped blob: only the header's colour space matters here."""
    raw = bytearray((bytes(range(256)) * (size // 256 + 1))[:size])
    raw[16:20] = space
    return bytes(raw)


def _photo() -> Image.Image:
    return Image.linear_gradient("L").resize((160, 120)).convert("RGB")


def _icc_of(path: Path) -> bytes | None:
    with Image.open(path) as img:
        return img.info.get("icc_profile")


@pytest.mark.parametrize("fmt", ["JPEG", "WEBP", "PNG", "TIFF"])
def test_compressing_keeps_the_colour_profile(tmp_path, fmt):
    ext = {"JPEG": "jpg", "WEBP": "webp", "PNG": "png", "TIFF": "tif"}[fmt]
    src = tmp_path / f"src.{ext}"
    _photo().save(src, format=fmt, icc_profile=SRGB)
    out = tmp_path / f"out.{ext}"
    compress_image(src, out, quality=70)
    assert _icc_of(out) == SRGB


@pytest.mark.parametrize("ext,fmt", [("jpg", "JPEG"), ("webp", "WEBP")])
def test_target_size_keeps_the_colour_profile(tmp_path, ext, fmt):
    """Through the quality search and the scaling rounds too."""
    src = tmp_path / f"src.{ext}"
    Image.effect_noise((800, 600), 90).convert("RGB").save(
        src, format=fmt, quality=95, icc_profile=SRGB
    )
    out = tmp_path / f"out.{ext}"
    result = compress_image_to_target(src, out, target_bytes=8 * 1024)
    assert result["converged"]
    assert result["resized_to"], "the noise only fits scaled down"
    assert _icc_of(out) == SRGB


def test_target_size_drops_a_profile_that_would_eat_the_target(tmp_path):
    """A print profile of some hundred KB against a 300 KB target goes (more
    than a quarter of the target); the result meets the target."""
    src = tmp_path / "print.jpg"
    big = _stand_in(b"RGB ", 557 * 1024)
    _photo().resize((800, 600)).save(src, format="JPEG", quality=95, icc_profile=big)
    out = tmp_path / "out.jpg"
    result = compress_image_to_target(src, out, target_bytes=300 * 1024)
    assert result["converged"]
    assert _icc_of(out) is None


def test_a_profile_over_four_mebibytes_goes(tmp_path):
    """Pillow splits a JPEG's profile in time growing with its square: a
    crafted 16 MB one made each encode cost most of a second. A print
    profile (up to about 2 MB) stays."""
    img = Image.new("RGB", (4, 4))
    img.info["icc_profile"] = _stand_in(b"RGB ", ICC_MAX_BYTES + 1)
    assert "icc_profile" not in strip_metadata(img).info
    img.info["icc_profile"] = _stand_in(b"RGB ", ICC_MAX_BYTES)
    assert strip_metadata(img).info["icc_profile"] == img.info["icc_profile"]


def test_webp_gets_no_greyscale_profile(tmp_path):
    """WebP writes colour whatever the source mode, so a greyscale profile
    would mislabel it."""
    get_supported_conversions()
    src = tmp_path / "grey.png"
    Image.new("LA", (32, 24), (128, 255)).save(src, format="PNG", icc_profile=_stand_in(b"GRAY"))
    out = tmp_path / "grey.webp"
    get_converter("png", "webp").convert(src, out, quality=80)
    assert _icc_of(out) is None
    assert icc_for(Image.new("L", (2, 2)), "WEBP") is None


@pytest.mark.parametrize(
    "src_ext,src_fmt,tgt",
    [
        ("png", "PNG", "jpg"),
        ("png", "PNG", "webp"),
        ("jpg", "JPEG", "webp"),
        ("jpg", "JPEG", "png"),
    ],
)
def test_converting_keeps_the_colour_profile(tmp_path, src_ext, src_fmt, tgt):
    get_supported_conversions()  # loads the converter modules
    src = tmp_path / f"src.{src_ext}"
    _photo().save(src, format=src_fmt, icc_profile=SRGB)
    out = tmp_path / f"out.{tgt}"
    get_converter(src_ext, tgt).convert(src, out, quality=80)
    assert _icc_of(out) == SRGB


def test_an_iphone_photo_keeps_its_colour_profile_as_jpg(tmp_path):
    """HEIC → JPG, the most common iPhone conversion."""
    pytest.importorskip("pillow_heif")
    conversions = get_supported_conversions()
    if "jpg" not in conversions.get("heic", []):
        pytest.skip("HEIC is not available in this build")
    src = tmp_path / "photo.heic"
    _photo().save(src, format="HEIF", quality=85, icc_profile=SRGB)
    assert _icc_of(src) == SRGB
    out = tmp_path / "photo.jpg"
    get_converter("heic", "jpg").convert(src, out, quality=85)
    assert _icc_of(out) == SRGB


def test_a_cmyk_profile_goes_with_the_conversion_to_rgb(tmp_path):
    """The converter turns CMYK into RGB; the CMYK profile would then make
    every viewer misread the colours."""
    get_supported_conversions()
    src = tmp_path / "print.jpg"
    _photo().convert("CMYK").save(src, format="JPEG", icc_profile=_stand_in(b"CMYK"))
    out = tmp_path / "web.jpg"
    get_converter("jpg", "webp").convert(src, out, quality=80)
    assert _icc_of(out) is None


@pytest.mark.parametrize(
    "mode,space,fits",
    [
        ("RGB", b"RGB ", True),
        ("RGBA", b"RGB ", True),
        ("P", b"RGB ", True),
        ("PA", b"RGB ", True),
        ("L", b"GRAY", True),
        ("LA", b"GRAY", True),
        ("I;16", b"GRAY", True),
        ("I;16B", b"GRAY", True),
        ("CMYK", b"CMYK", True),
        ("LAB", b"Lab ", True),
        ("RGB", b"Lab ", False),
        ("RGB", b"CMYK", False),
        ("RGB", b"GRAY", False),
        ("L", b"RGB ", False),
    ],
)
def test_a_profile_fits_only_its_own_kind_of_pixels(mode, space, fits):
    assert _icc_fits(mode, _stand_in(space)) is fits
    img = Image.new(mode, (4, 4))
    img.info["icc_profile"] = _stand_in(space)
    assert ("icc_profile" in strip_metadata(img).info) is fits


def test_a_short_profile_goes():
    assert not _icc_fits("RGB", b"RGB ")
