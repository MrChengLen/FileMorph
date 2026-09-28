# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for core security, utilities, and quota definitions."""

import inspect

import pytest

from app.core import security
from app.core.quotas import QUOTAS, get_quota
from app.core.utils import safe_download_name
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


def test_safe_download_name_normal():
    assert safe_download_name("photo.jpg") == "photo.jpg"


def test_safe_download_name_path_traversal():
    result = safe_download_name("../../etc/passwd.jpg")
    assert ".." not in result
    assert "/" not in result


def test_safe_download_name_null_bytes():
    result = safe_download_name("file\x00name.jpg")
    assert "\x00" not in result


def test_safe_download_name_unicode():
    result = safe_download_name("Ünïcödé.pdf")
    assert isinstance(result, str)
    assert len(result) > 0


def test_safe_download_name_empty():
    assert safe_download_name("") == "result"


def test_safe_download_name_max_length():
    assert len(safe_download_name("a" * 300 + ".jpg")) <= 200


@pytest.mark.parametrize("suffix", [".png", "_pdfa.pdf", "_compressed.jpg", ".redacted.pdf"])
def test_safe_download_name_truncation_keeps_suffix(suffix):
    # Only the stem is shortened — a cut ".pn" / "_pdfa.pd" won't open.
    assert safe_download_name("a" * 250, suffix) == "a" * (200 - len(suffix)) + suffix


def test_safe_download_name_nfkd_growth_keeps_suffix():
    # NFKD splits 한 into 3 jamo, so a 70-character stem sanitises to 210:
    # cutting the raw stem before sanitising can't catch it.
    result = safe_download_name("한" * 70, ".png")
    assert len(result) == 200
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
        ("Ünïcödé", "Unicode.jpg"),
        (" .draft. ", "draft. .jpg"),
    ],
)
def test_safe_download_name_unchanged_when_it_fits(stem, expected):
    # Same output as the old one-argument call on the joined name.
    assert safe_download_name(stem, ".jpg") == expected
    assert safe_download_name(stem + ".jpg") == expected


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
