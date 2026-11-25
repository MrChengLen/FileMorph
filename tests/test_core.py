# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for core security, utilities, and quota definitions."""

import inspect
import unicodedata

import pytest

from app.core import security
from app.core.quotas import QUOTAS, get_quota
from app.core.utils import content_disposition, safe_download_name
from tests.conftest import TEST_KEY


# ---------------------------------------------------------------------------
# validate_api_key
# ---------------------------------------------------------------------------


def test_validate_correct_key(setup_test_api_key):
    assert security.validate_api_key(TEST_KEY) is True


def test_validate_wrong_key(setup_test_api_key):
    assert security.validate_api_key("not-the-right-key") is False


def test_validate_empty_key(setup_test_api_key):
    assert security.validate_api_key("") is False


def test_validate_key_uses_compare_digest():
    src = inspect.getsource(security.validate_api_key)
    assert "compare_digest" in src


# ---------------------------------------------------------------------------
# safe_download_name
# ---------------------------------------------------------------------------


def test_safe_download_name_null_bytes():
    result = safe_download_name("file\x00name.jpg")
    assert "\x00" not in result


def test_safe_download_name_empty():
    assert safe_download_name("") == "result"


@pytest.mark.parametrize("suffix", [".png", "_pdfa.pdf", "_compressed.jpg", ".redacted.pdf"])
def test_safe_download_name_truncation_keeps_suffix(suffix):
    # Only the stem is shortened — a cut ".pn" / "_pdfa.pd" won't open.
    assert safe_download_name("a" * 250, suffix) == "a" * (200 - len(suffix)) + suffix


def test_safe_download_name_cap_counts_utf8_bytes():
    # File systems count a name's bytes: 70 × "한" are 210 of them. The cut
    # keeps whole characters (65 × 3 bytes + ".png" = 199).
    assert safe_download_name("한" * 70, ".png") == "한" * 65 + ".png"


def test_safe_download_name_growth_keeps_suffix():
    # NFC splits the Hebrew presentation form U+FB2C (3 bytes) into three
    # code points of 2 bytes each, so a 40-character stem of 120 bytes
    # sanitises to 240: cutting the raw stem before sanitising can't catch it.
    result = safe_download_name(chr(0xFB2C) * 40, ".png")
    assert len(result.encode("utf-8")) == 200
    assert result.endswith(".png")


def test_safe_download_name_cut_leaves_no_dot_before_suffix():
    assert safe_download_name("x" * 195 + ". more words", ".png") == "x" * 195 + ".png"


def test_safe_download_name_overlong_suffix_is_cut():
    # The suffix can carry a user-controlled extension (batch rows are named
    # before validation); one that leaves no room for the stem is cut whole.
    assert safe_download_name("photo", "." + "x" * 300) == ("photo." + "x" * 300)[:200]


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        ("photo", "photo.jpg"),
        ("../../etc/passwd", "etcpasswd.jpg"),
        ("Ünïcödé", "Ünïcödé.jpg"),
        (" .draft. ", "draft. .jpg"),
    ],
)
def test_safe_download_name_unchanged_when_it_fits(stem, expected):
    # Same output as the old one-argument call on the joined name.
    assert safe_download_name(stem, ".jpg") == expected
    assert safe_download_name(stem + ".jpg") == expected


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        # Letters of every script keep their accents ("Grüße", not "Gruße").
        ("Grüße an Oma", "Grüße an Oma.png"),
        ("Отчёт", "Отчёт.png"),
        ("写真", "写真.png"),
        # A name from macOS spells "ü" as "u" plus a combining mark: one "ü".
        (unicodedata.normalize("NFD", "Grüße"), "Grüße.png"),
        # Punctuation and symbols stay.
        ("foto (1)", "foto (1).png"),
        ("50% & mehr", "50% & mehr.png"),
        ("€€€", "€€€.png"),
        # The quote would end the header's quoted string. A browser's form
        # upload sends it, and CR and LF, as %22, %0D and %0A.
        ('say "hi"', "say hi.png"),
        ("Angebot %22final%22", "Angebot final.png"),
        ("zwei%0D%0AZeilen", "zweiZeilen.png"),
        # Path separators and what Windows forbids in a name.
        ("a/b" + chr(92) + "c:d*e?f<g>h|i", "abcdefghi.png"),
        # A bidi override would show "evil" + "exe.png"; control characters.
        ("evil" + chr(0x202E) + "gnp.exe", "evilgnp.exe.png"),
        ("tab" + chr(9) + "null" + chr(0), "tabnull.png"),
    ],
)
def test_safe_download_name_keeps_the_upload_s_name(stem, expected):
    assert safe_download_name(stem, ".png") == expected


@pytest.mark.parametrize(
    "stem", ["", "???", "...", " . ", "<>|", chr(0x202E), chr(0x3000) + "." + chr(0x3000)]
)
def test_safe_download_name_empty_stem_keeps_the_suffix(stem):
    # Nothing of the stem is left but dots and white space (U+3000 is the
    # ideographic space): the fallback stem, never a bare "png" or ". .png".
    assert safe_download_name(stem, ".png") == "result.png"


# ---------------------------------------------------------------------------
# content_disposition
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["photo.png", "Mein Urlaub (1).png", "it's #1, ok.zip"])
def test_content_disposition_plain_ascii_name(name):
    assert content_disposition(name) == f'attachment; filename="{name}"'


@pytest.mark.parametrize(
    ("name", "stand_in", "encoded"),
    [
        ("Grüße an Oma.png", "Gru_e an Oma.png", "Gr%C3%BC%C3%9Fe%20an%20Oma.png"),
        ("café.png", "cafe.png", "caf%C3%A9.png"),
        ("Отчёт_pages.zip", "______pages.zip", "%D0%9E%D1%82%D1%87%D1%91%D1%82_pages.zip"),
        # Characters the plain form can't carry as they are.
        ("50% off.png", "50_ off.png", "50%25%20off.png"),
        ('a"b.png', "a_b.png", "a%22b.png"),
    ],
)
def test_content_disposition_carries_both_forms(name, stand_in, encoded):
    assert content_disposition(name) == (
        f"attachment; filename=\"{stand_in}\"; filename*=UTF-8''{encoded}"
    )


def test_content_disposition_never_breaks_the_header():
    # Even a name that skipped safe_download_name: ASCII only, no line break.
    hostile = "a" + chr(13) + chr(10) + 'Set-Cookie: x="1"' + chr(0x202E) + "ü"
    value = content_disposition(hostile)
    assert value.isascii()
    assert chr(13) not in value and chr(10) not in value


# What a download name never carries, and every character NFKD turns into one
# of them: "／" becomes "/" in the header's ASCII copy.
_UNSAFE = set('"*/:<>?|') | {chr(92)}
_LOOKALIKES = [
    chr(cp)
    for cp in range(0x80, 0x110000)
    if not 0xD800 <= cp <= 0xDFFF and not _UNSAFE.isdisjoint(unicodedata.normalize("NFKD", chr(cp)))
]


def test_safe_download_name_drops_lookalikes_of_unsafe_characters():
    assert len(_LOOKALIKES) >= 20  # "／", "？", "＼", "：" … — something to check
    for char in _LOOKALIKES:
        assert safe_download_name("a" + char + "b", ".png") == "ab.png", f"U+{ord(char):04X}"


def test_content_disposition_ascii_copy_carries_no_unsafe_character():
    # Even for a name that skipped safe_download_name.
    for char in _LOOKALIKES:
        value = content_disposition("a" + char + "b.png")
        plain = value.split('filename="', 1)[1].split('"', 1)[0]
        assert _UNSAFE.isdisjoint(plain), f"U+{ord(char):04X} in {value}"


def test_content_disposition_ascii_copy_hides_no_file():
    # A fullwidth dot decomposes to "." — the copy would name a hidden file.
    assert content_disposition(chr(0xFF0E) + "bashrc.png") == (
        "attachment; filename=\"_bashrc.png\"; filename*=UTF-8''%EF%BC%8Ebashrc.png"
    )


# ---------------------------------------------------------------------------
# Quota definitions
# ---------------------------------------------------------------------------


def test_quota_all_tiers_defined():
    for tier in ("anonymous", "free", "pro", "business", "enterprise"):
        assert tier in QUOTAS


def test_quota_enterprise_unlimited():
    q = QUOTAS["enterprise"]
    assert q.conversions_per_day is None
    assert q.api_calls_per_month is None


def test_quota_get_unknown_tier():
    q = get_quota("nonexistent-tier")
    assert q == QUOTAS["anonymous"]


def test_quota_file_size_ascending():
    sizes = [QUOTAS[t].max_file_size_bytes for t in ("anonymous", "free", "pro", "business")]
    assert sizes == sorted(sizes)
