# SPDX-License-Identifier: AGPL-3.0-or-later
"""Limit messages name the free way past a limit, never an upgrade.

The hosted service has no paid plan to upgrade to, so a request that hits a
tier limit is told what it can do for free: anonymous callers can register for
the free tier, everyone else can run FileMorph themselves (product rule: the
free alternative first). A free account is only offered where accounts exist:
a Community Edition instance has no database and signing up answers 503 there,
so every caller is pointed to self-hosting. The AI routes keep their wording —
AI operations are a paid add-on behind their own flag.
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
from app.db.base import accounts_enabled

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


def test_accounts_exist_only_with_a_session_factory(accounts):
    assert accounts_enabled() is accounts


def test_register_is_a_dead_end_without_accounts(client):
    """Why the Community Edition messages offer no free account."""
    assert not accounts_enabled()
    res = client.post(
        "/api/v1/auth/register", json={"email": "a@example.com", "password": "x" * 12}
    )
    assert res.status_code == 503, res.text


def test_higher_cap_hint_points_to_the_free_path(accounts):
    anonymous = (
        "Register free for a higher cap." if accounts else "Self-host FileMorph for a higher cap."
    )
    assert higher_cap_hint("anonymous") == anonymous
    for tier in ("free", "pro", "business", "enterprise"):
        assert higher_cap_hint(tier) == "Self-host FileMorph for a higher cap."


def test_file_too_large_message_points_to_the_free_path(accounts):
    free_mb = QUOTAS["free"].max_file_size_bytes // _MB
    hint = (
        f"Register free to upload up to {free_mb} MB."
        if accounts
        else "Self-host FileMorph for larger files."
    )
    assert file_too_large_message("anonymous", 30 * _MB) == (
        f"File too large (30 MB max for anonymous). {hint}"
    )
    assert file_too_large_message("free", 100 * _MB) == (
        "File too large (100 MB max for your plan). Self-host FileMorph for larger files."
    )


def test_larger_batches_hint_names_the_free_batch_size(accounts):
    free_batch = QUOTAS["free"].max_files_per_batch
    anonymous = (
        f"Register free to send up to {free_batch} files per request."
        if accounts
        else "Self-host FileMorph for larger batches."
    )
    assert larger_batches_hint("anonymous") == anonymous
    assert larger_batches_hint("free") == "Self-host FileMorph for larger batches."


@pytest.mark.parametrize(
    "path, data",
    [
        ("/api/v1/convert/batch", {"target_formats": ["png", "png"]}),
        ("/api/v1/compress/batch", {"quality": "80"}),
    ],
)
def test_anonymous_batch_over_the_limit_names_the_free_path(
    client, sample_jpg, accounts, path, data
):
    jpg = sample_jpg.read_bytes()
    files = [("files", (f"{i}.jpg", jpg, "image/jpeg")) for i in range(2)]
    res = client.post(path, files=files, data=data)
    assert res.status_code == 400, res.text
    assert res.headers.get("X-FileMorph-Error-Code") == "batch_too_large"
    detail = res.json()["detail"]
    assert detail.startswith("Batch size 2 exceeds tier limit of 1.")
    free_batch = QUOTAS["free"].max_files_per_batch
    hint = (
        f"Register free to send up to {free_batch} files per request."
        if accounts
        else "Self-host FileMorph for larger batches."
    )
    assert detail.endswith(hint), detail


def test_anonymous_one_file_batch_over_the_output_cap_names_the_free_path(
    client, sample_jpg, monkeypatch, accounts
):
    """A batch of one is allowed without an account; its output-cap hint points
    to the free tier where accounts exist, else to self-hosting."""
    tiny = dataclasses.replace(QUOTAS["anonymous"], output_cap_bytes=1)
    monkeypatch.setitem(QUOTAS, "anonymous", tiny)
    files = [("files", ("a.jpg", sample_jpg.read_bytes(), "image/jpeg"))]
    res = client.post("/api/v1/convert/batch", files=files, data={"target_formats": ["png"]})
    assert res.status_code == 422, res.text
    message = res.json()["files"][0]["error_message"]
    hint = (
        "Register free for a higher cap." if accounts else "Self-host FileMorph for a higher cap."
    )
    assert message.endswith("Try WebP/AVIF. " + hint), message


# ── the web UI ───────────────────────────────────────────────────────────────

_UI_LIMIT_KEYS = (
    "errorInputTooLarge",
    "errorOutputCapExceeded",
    "errorTargetSizeExceedsCap",
    "errorBatchTooLarge",
)
_REGISTER = {"en": "register free", "de": "registriere dich kostenlos"}


def _js_strings(client, locale: str) -> dict[str, str]:
    html = client.get(f"/{locale}/").text
    blob = re.search(
        r'<script id="fm-i18n-strings" type="application/json">(.*?)</script>', html, re.S
    )
    assert blob, "FM_I18N block missing"
    return json.loads(blob.group(1))


@pytest.mark.parametrize("locale", ["en", "de"])
def test_ui_limit_texts_offer_no_upgrade(client, accounts, locale):
    """The FM_I18N texts the web UI shows for the limit codes name self-hosting,
    and the free account only where accounts exist."""
    strings = _js_strings(client, locale)
    for key in _UI_LIMIT_KEYS:
        text = strings[key]
        assert "upgrad" not in text.lower(), (locale, key, text)
        assert "FileMorph" in text, (locale, key, "names self-hosting")
        assert (_REGISTER[locale] in text.lower()) is accounts, (locale, key, text)


# The batch texts spell the batch sizes out: changing them in quotas.py fails
# the test below until the catalog follows.
_FREE_BATCH = QUOTAS["free"].max_files_per_batch
_BATCH_TEXTS = {
    ("en", False): (
        "Too many files at once. Select one file at a time or self-host FileMorph — "
        "there you set the limits."
    ),
    ("en", True): (
        "Too many files at once. Select fewer files or self-host FileMorph — there you "
        "set the limits. No account yet? Then it's one file at a time — "
        f"register free for up to {_FREE_BATCH} at once."
    ),
    ("de", False): (
        "Zu viele Dateien auf einmal. Wähle jeweils eine Datei aus oder hoste FileMorph "
        "selbst – dort legst du die Grenzen selbst fest."
    ),
    ("de", True): (
        "Zu viele Dateien auf einmal. Wähle weniger Dateien aus oder hoste FileMorph "
        "selbst – dort legst du die Grenzen selbst fest. Noch kein Konto? Dann geht "
        f"jeweils eine Datei – registriere dich kostenlos für bis zu {_FREE_BATCH} auf einmal."
    ),
}


@pytest.mark.parametrize("locale", ["en", "de"])
def test_ui_batch_text_spells_out_the_batch_sizes(client, accounts, locale):
    assert QUOTAS["anonymous"].max_files_per_batch == 1, "the texts say one file at a time"
    assert _js_strings(client, locale)["errorBatchTooLarge"] == _BATCH_TEXTS[locale, accounts]


def test_web_ui_shows_the_localized_batch_text():
    js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
    assert "errCode === 'batch_too_large'" in js, "app.js ignores the batch_too_large code"
    assert "i18n.errorBatchTooLarge" in js, "app.js never shows the localized batch text"
    upsell = re.search(r"const UPSELL_ERROR_CODES = \[(.*?)\];", js)
    assert upsell, "UPSELL_ERROR_CODES not found in app.js"
    assert "'batch_too_large'" in upsell.group(1), "no limits link next to the batch text"
    branch = js[js.index("res.status === 400 && data.detail") : js.index("res.status === 401")]
    assert "showError(msg, errCode)" in branch, "the 400 branch never passes the code on"


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
