# SPDX-License-Identifier: AGPL-3.0-or-later
"""Limit messages name the free way past a limit, never an upgrade.

The hosted service has no paid plan to upgrade to, so a request that hits a
tier limit is told what it can do for free: anonymous callers can register for
the free tier, everyone else can run FileMorph themselves (product rule: the
free alternative first). The AI routes keep their wording — AI operations are
a paid add-on behind their own flag.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.quotas import (
    _MB,
    QUOTAS,
    file_too_large_message,
    higher_cap_hint,
    larger_batches_hint,
)
from app.core.templates import templates

ROOT = Path(__file__).resolve().parent.parent

# Every module that builds a tier-limit message for the file routes.
_LIMIT_MESSAGE_MODULES = (
    "app/api/routes/convert.py",
    "app/api/routes/compress.py",
    "app/api/routes/pdf_pages.py",
    "app/core/usage.py",
    "app/core/concurrency.py",
    "app/core/quotas.py",
)
_UPSELL = re.compile(r"upgrad", re.IGNORECASE)


@pytest.mark.parametrize("path", _LIMIT_MESSAGE_MODULES)
def test_limit_messages_offer_no_upgrade(path):
    source = (ROOT / path).read_text(encoding="utf-8")
    strings = re.findall(r'"[^"\n]*"', source)  # string literals, not comments
    hits = [s for s in strings if _UPSELL.search(s)]
    assert not hits, f"{path} still offers an upgrade: {hits}"


def test_higher_cap_hint_points_to_the_free_path():
    assert higher_cap_hint("anonymous") == "Register free for a higher cap."
    for tier in ("free", "pro", "business", "enterprise"):
        assert higher_cap_hint(tier) == "Self-host FileMorph for a higher cap."


def test_file_too_large_message_points_to_the_free_path():
    free_mb = QUOTAS["free"].max_file_size_bytes // _MB
    assert file_too_large_message("anonymous", 30 * _MB) == (
        f"File too large (30 MB max for anonymous). Register free to upload up to {free_mb} MB."
    )
    assert file_too_large_message("free", 100 * _MB) == (
        "File too large (100 MB max for your plan). Self-host FileMorph for larger files."
    )


def test_larger_batches_hint_names_the_free_batch_size():
    free_batch = QUOTAS["free"].max_files_per_batch
    assert larger_batches_hint("anonymous") == (
        f"Register free to send up to {free_batch} files per request."
    )
    assert larger_batches_hint("free") == "Self-host FileMorph for larger batches."


@pytest.mark.parametrize(
    "path, data",
    [
        ("/api/v1/convert/batch", {"target_formats": ["png", "png"]}),
        ("/api/v1/compress/batch", {"quality": "80"}),
    ],
)
def test_anonymous_batch_over_the_limit_is_pointed_to_the_free_tier(client, sample_jpg, path, data):
    jpg = sample_jpg.read_bytes()
    files = [("files", (f"{i}.jpg", jpg, "image/jpeg")) for i in range(2)]
    res = client.post(path, files=files, data=data)
    assert res.status_code == 400, res.text
    detail = res.json()["detail"]
    assert detail.startswith("Batch size 2 exceeds tier limit of 1.")
    assert detail.endswith(larger_batches_hint("anonymous"))


def test_anonymous_one_file_batch_over_the_output_cap_is_pointed_to_the_free_tier(
    client, sample_jpg, monkeypatch
):
    """A batch of one is allowed without an account; its output-cap hint must
    still point to the free tier, not to self-hosting."""
    tiny = dataclasses.replace(QUOTAS["anonymous"], output_cap_bytes=1)
    monkeypatch.setitem(QUOTAS, "anonymous", tiny)
    files = [("files", ("a.jpg", sample_jpg.read_bytes(), "image/jpeg"))]
    res = client.post("/api/v1/convert/batch", files=files, data={"target_formats": ["png"]})
    assert res.status_code == 422, res.text
    message = res.json()["files"][0]["error_message"]
    assert message.endswith("Try WebP/AVIF. " + higher_cap_hint("anonymous")), message


def test_ui_limit_texts_offer_no_upgrade(client):
    """The FM_I18N texts the web UI shows for the three 413 codes (EN and DE)."""
    for locale in ("en", "de"):
        html = client.get(f"/{locale}/").text
        blob = re.search(
            r'<script id="fm-i18n-strings" type="application/json">(.*?)</script>', html, re.S
        )
        assert blob, "FM_I18N block missing"
        strings = json.loads(blob.group(1))
        for key in ("errorInputTooLarge", "errorOutputCapExceeded", "errorTargetSizeExceedsCap"):
            text = strings[key]
            assert "upgrad" not in text.lower(), (locale, key, text)
            assert "FileMorph" in text, (locale, key, "names self-hosting")


@pytest.mark.parametrize("path", ["/en/", "/en/pdf/split"])
@pytest.mark.parametrize(
    "stripe, label",
    [(False, "Costs and limits →"), (True, "See plans and limits →")],
    ids=["free", "plans"],
)
def test_limit_error_link_names_plans_only_where_they_can_be_booked(
    client, monkeypatch, path, stripe, label
):
    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    monkeypatch.setitem(templates.env.globals, "pricing_enabled", True)
    monkeypatch.setitem(templates.env.globals, "stripe_enabled", stripe)
    html = client.get(path).text
    link = re.search(r'<a id="(?:convert|pdf)-error-upsell"[^>]*>([^<]*)</a>', html)
    assert link, f"{path}: the limit-error link is missing"
    assert link.group(1).strip() == label
