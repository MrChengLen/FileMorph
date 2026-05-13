# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for core security, utilities, and quota definitions."""

import inspect

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
