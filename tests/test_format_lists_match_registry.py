# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every hand-written list of input formats must match the converter registry.

The homepage drop-zone caption is pinned by test_homepage_drop_zone_modes.py.
The same list is written out by hand in four more places, which had fallen
behind it (HEIF, AVIF, ICO, HTML, EML, FLV, WMV, AAC, WMA and Opus missing;
the README table only lacked HTML/EML inputs and image → PDF):

- the homepage FAQ answer "Which file formats can I convert?" (EN + DE)
- the "FileMorph converts …" sentence in /llms.txt
- the "Convert …" entries of the JSON-LD featureList
- README.md: the drop-zone mockup and the "Supported Formats" table

They stay hand-written (the FAQ answer is translated, the README is static
Markdown), so each test compares one of them with get_public_conversions() —
the data /api/v1/formats serves. A new input format added without updating the
text fails CI, and the message names the surface and the missing formats.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.converters.registry import get_public_conversions
from app.core.jsonld import build_site_jsonld

README = Path(__file__).resolve().parent.parent / "README.md"

# Other spellings of the same format — the text names each format once.
_ALIAS = {"jpeg": "jpg", "tif": "tiff", "htm": "html", "markdown": "md", "pdf/a-2b": "pdfa"}


def _alias(fmt: str) -> str:
    return _ALIAS.get(fmt, fmt)


def _assert_matches_registry(found: set[str], where: str) -> None:
    expected = {_alias(src) for src in get_public_conversions()}
    missing, extra = sorted(expected - found), sorted(found - expected)
    assert found == expected, (
        f"{where} drifted from the converter registry — missing: {missing}, extra: {extra}"
    )


def _paren_tokens(text: str) -> set[str]:
    """Lowercased format names from every "(A, B, C)" group in prose such as
    "Images (HEIC, JPG), documents (PDF) and video (MP4)"."""
    return {
        _alias(name.strip().lower())
        for group in re.findall(r"\(([^)]*)\)", text)
        for name in group.split(",")
    }


def _cell_tokens(cell: str) -> set[str]:
    """Lowercased format names from a README table cell such as
    "DOCX, TXT, Markdown (`.md`)" or "TXT, PDF/A-2b<sup>†</sup>" — footnote
    markup and a note after the name are dropped."""
    cell = re.sub(r"<[^>]+>|†", "", cell)
    return {_alias(part.split()[0].lower()) for part in cell.split(",") if part.strip()}


@pytest.mark.parametrize(
    ("prefix", "question", "first_word"),
    [
        ("/en", "Which file formats can I convert?", "Images"),
        ("/de", "Welche Dateiformate kann ich konvertieren?", "Bilder"),
    ],
)
def test_faq_format_answer_matches_registry(client, prefix, question, first_word):
    html = client.get(f"{prefix}/").text
    match = re.search(re.escape(question) + r"</h3>\s*<p[^>]*>(.*?)</p>", html, re.S)
    assert match, f"FAQ question {question!r} not found on {prefix}/"
    answer = match.group(1).strip()
    # A fuzzy catalogue entry is left out at compile time, so /de/ would fall
    # back to the English answer — same formats, wrong language. Check both.
    assert answer.startswith(f"{first_word} ("), (
        f"FAQ answer on {prefix}/ is not in the page language: {answer!r}"
    )
    _assert_matches_registry(_paren_tokens(answer), f"FAQ answer ({prefix}/)")


def test_llms_txt_format_sentence_matches_registry(client):
    body = client.get("/llms.txt").text
    match = re.search(r"FileMorph converts (.+?\))\.", body)
    assert match, "llms.txt lost its 'FileMorph converts …' sentence"
    _assert_matches_registry(_paren_tokens(match.group(1)), "llms.txt")


def test_jsonld_convert_features_match_registry():
    canonical, _ = build_site_jsonld("https://files.example.com")
    webapp = next(i for i in json.loads(canonical) if i["@type"] == "WebApplication")
    converts = [f for f in webapp["featureList"] if f.startswith("Convert ")]
    assert converts, "JSON-LD featureList has no 'Convert …' entries"
    tokens = {fmt for feature in converts for fmt in _paren_tokens(feature)}
    _assert_matches_registry(tokens, "JSON-LD featureList")


def test_readme_drop_zone_mockup_matches_registry():
    """The ASCII mockup mirrors the homepage caption: its format lines sit
    between "or click to browse" and the drop zone's bottom border."""
    _, found, rest = README.read_text(encoding="utf-8").partition("or click to browse")
    assert found, "README drop-zone mockup not found ('or click to browse')"
    tokens: set[str] = set()
    for line in rest.split("└", 1)[0].splitlines()[1:]:
        cells = line.split("│")  # outer border, drop-zone border, content, …
        if len(cells) > 2:
            tokens |= {_alias(t.strip().lower()) for t in cells[2].split("·") if t.strip()}
    _assert_matches_registry(tokens, "README drop-zone mockup")


def _readme_format_table() -> dict[str, tuple[set[str], set[str]]]:
    """Row label → (input formats, output formats) of README's
    "## Supported Formats" table."""
    _, found, rest = README.read_text(encoding="utf-8").partition("## Supported Formats")
    assert found, "README '## Supported Formats' heading not found"
    section = rest.split("\n## ", 1)[0]
    rows = re.findall(r"^\|\s*\*\*(.+?)\*\*\s*\|(.*?)\|(.*?)\|\s*$", section, re.M)
    return {label: (_cell_tokens(inp), _cell_tokens(out)) for label, inp, out in rows}


def test_readme_format_table_inputs_match_registry():
    rows = _readme_format_table()
    assert rows, "README 'Supported Formats' table not found"
    inputs = {fmt for ins, _ in rows.values() for fmt in ins}
    _assert_matches_registry(inputs, "README 'Supported Formats' table (inputs)")


def test_readme_format_table_outputs_match_registry():
    """Each row's Output column names the union of what its inputs convert to
    (the table doesn't say which input reaches which output)."""
    conversions = get_public_conversions()
    for label, (ins, outs) in _readme_format_table().items():
        sources = [src for src in conversions if _alias(src) in ins]
        expected = {_alias(tgt) for src in sources for tgt in conversions[src]}
        assert outs == expected, (
            f"README table row {label!r}: outputs drifted from the converter registry — "
            f"missing: {sorted(expected - outs)}, extra: {sorted(outs - expected)}"
        )
