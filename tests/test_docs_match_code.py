# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public docs quote limits from the code — pin them so they cannot drift.

The pricing page reads ``app/core/quotas.py`` directly; the markdown docs copy
the numbers by hand, and they drifted. After the 2026-05-25 pricing overhaul
the API guide still showed the old tier table (plus a per-tier "API/min"
column, although the rate limit is per IP and the same for every tier), three
docs said anonymous uploads cap at 20 MB, and the self-hosting guide gave Pro
and Business the old concurrency caps. These tests read the numbers back out
of the markdown and compare them with the code, so the next quota change fails
CI until the docs follow.

A "not found" failure means a sentence was reworded: check the new wording
against the code, then update the pattern here.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pytest

from app.core.batch import BatchFileResult, build_batch_zip
from app.core.config import Settings
from app.core.quotas import _MB, QUOTAS

DOCS = Path(__file__).resolve().parent.parent / "docs"


def _text(doc: str) -> str:
    return (DOCS / doc).read_text(encoding="utf-8")


def _section(doc: str, heading: str) -> str:
    """The text under the line ``heading`` in ``docs/<doc>``, up to the next heading."""
    text = _text(doc)
    assert f"\n{heading}\n" in text, f"{doc}: heading {heading!r} not found"
    body = text[text.index(f"\n{heading}\n") + len(heading) + 2 :]
    return body.split("\n#", 1)[0]


def _first_table(markdown: str) -> list[dict[str, str]]:
    """The first markdown table in ``markdown``, one dict per body row."""
    lines = markdown.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("|")), None)
    assert start is not None, "no markdown table under this heading"
    rows = []
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    header, _separator, *body = rows
    return [dict(zip(header, row)) for row in body]


def _mb(cell: str) -> int:
    number, unit = cell.split()
    assert unit == "MB", cell
    return int(number) * _MB


def _calls(cell: str) -> int | None:
    """``1,000`` / ``1 000`` → 1000, ``unlimited`` → None, ``n/a`` → 0 (the
    anonymous value: no account, so no monthly counter — only the per-IP rate
    limit)."""
    if cell == "unlimited":
        return None
    if cell.startswith("n/a"):
        return 0
    return int(cell.replace(",", "").replace(" ", ""))


# API-guide column → (TierQuota field, cell parser).
_GUIDE_COLUMNS = {
    "Max file size": ("max_file_size_bytes", _mb),
    "Max files / batch": ("max_files_per_batch", int),
    "Output cap": ("output_cap_bytes", _mb),
    "Concurrent requests": ("concurrency", int),
    "API calls / month": ("api_calls_per_month", _calls),
}


def test_api_guide_tier_table_matches_quotas():
    rows = _first_table(_section("api-usage-guide.md", "## Tier Quotas & Discovery"))
    # An extra column fails here on purpose. The old "API/min" column promised
    # paid tiers 60/min, but the rate limit is per client IP and per route, the
    # same for every tier (the @limiter.limit decorators on the routes).
    assert set(rows[0]) == {"Tier", *_GUIDE_COLUMNS}
    assert [row["Tier"] for row in rows] == list(QUOTAS)
    for row in rows:
        quota = QUOTAS[row["Tier"]]
        for column, (field, parse) in _GUIDE_COLUMNS.items():
            assert parse(row[column]) == getattr(quota, field), (
                f"{row['Tier']} / {column}: the doc says {row[column]!r}, "
                f"quotas.py says {getattr(quota, field)!r}"
            )


def test_api_reference_monthly_quota_table_matches_quotas():
    section = _section("api-reference.md", "### Monthly call quota (per user)")
    documented = {
        row["Tier"].lower(): _calls(row["Monthly API calls"]) for row in _first_table(section)
    }
    assert documented == {tier: q.api_calls_per_month for tier, q in QUOTAS.items()}
    # The example 429 body quotes a tier's limit as app/core/usage.py prints it.
    examples = re.findall(r"\((\d+) per month for tier '(\w+)'\)", section)
    assert examples, "api-reference.md: the example 429 body was not found"
    for limit, tier in examples:
        assert int(limit) == QUOTAS[tier].api_calls_per_month, f"429 example: {tier}"


@pytest.mark.parametrize(
    "doc, pattern",
    [
        ("api-usage-guide.md", r"\*\*(\d+) MB\*\* per file"),
        ("security-overview.md", r"Anonymous uploads cap at (\d+) MB"),
        ("vendor-security-questionnaire.md", r"Size cap, per tier\*\* — anonymous (\d+) MB"),
    ],
)
def test_docs_quote_the_anonymous_upload_cap(doc, pattern):
    text = " ".join(_text(doc).split())  # undo the markdown line wraps
    found = re.findall(pattern, text)
    assert found, f"{doc}: the anonymous size-cap sentence was not found"
    assert {int(n) * _MB for n in found} == {QUOTAS["anonymous"].max_file_size_bytes}


def test_docs_quote_the_default_request_cap():
    """``MAX_UPLOAD_SIZE_MB`` caps every whole request before any tier limit."""
    default = Settings.model_fields["max_upload_size_mb"].default
    quoted = {}
    for doc in sorted(DOCS.glob("*.md")):
        text = " ".join(doc.read_text(encoding="utf-8").split())
        found = re.findall(r"MAX_UPLOAD_SIZE_MB`? \(default:? (\d+)", text)
        if found:
            quoted[doc.name] = {int(n) for n in found}
    assert quoted, "no doc quotes the MAX_UPLOAD_SIZE_MB default any more"
    assert quoted == {name: {default} for name in quoted}


def test_self_hosting_quotes_the_per_tier_concurrency():
    text = " ".join(_text("self-hosting.md").split())
    match = re.search(
        r"anonymous and free get (\d+) concurrent request, "
        r"Pro (\d+), Business (\d+), Enterprise (\d+)",
        text,
    )
    assert match, "self-hosting.md: the per-tier concurrency sentence was not found"
    anonymous_and_free, pro, business, enterprise = map(int, match.groups())
    documented = {
        "anonymous": anonymous_and_free,
        "free": anonymous_and_free,
        "pro": pro,
        "business": business,
        "enterprise": enterprise,
    }
    assert documented == {tier: q.concurrency for tier, q in QUOTAS.items()}


def test_api_guide_duplicate_name_example_matches_build_batch_zip():
    same = BatchFileResult(name="a.png", status="ok", size_in=1, size_out=1, content=b"x")
    zip_bytes, _summary = build_batch_zip([same] * 3, operation="convert", duration_ms=0)
    names = zipfile.ZipFile(io.BytesIO(zip_bytes)).namelist()
    assert names == ["a.png", "a_1.png", "a_2.png"]
    paragraph = _section("api-usage-guide.md", "### Duplicate filenames").strip().split("\n\n")[0]
    for name in names[1:]:
        assert f"`{name}`" in paragraph, f"the guide's duplicate-name example lacks {name}"
