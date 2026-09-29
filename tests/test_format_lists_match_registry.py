# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every hand-written list of input formats must match the converter registry.

The homepage drop-zone caption is pinned by test_homepage_drop_zone_modes.py.
The same list is written out by hand in five more places, which had fallen
behind it (HEIF, AVIF, ICO, HTML, EML, FLV, WMV, AAC, WMA and Opus missing;
the README table only lacked HTML/EML inputs and image → PDF; docs/formats.md
had no ICO row, left ICO out of five image rows and lacked PDF → PDF/A):

- the homepage FAQ answer "Which file formats can I convert?" (EN + DE)
- the "FileMorph converts …" sentence in /llms.txt
- the "Convert …" entries of the JSON-LD featureList
- README.md: the drop-zone mockup and the "Supported Formats" table
- docs/formats.md: the From → To conversion tables and the Audio/Video
  format lists ("any of the above can be converted to any other format")

They stay hand-written (the FAQ answer is translated, the README and
docs/formats.md are static Markdown), so each test compares one of them with
get_public_conversions() — the data /api/v1/formats serves. A new input format
added without updating the text fails CI, and the message names the surface
and the missing formats.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.converters.registry import get_public_conversions
from app.core.jsonld import build_site_jsonld

README = Path(__file__).resolve().parent.parent / "README.md"
FORMATS_MD = Path(__file__).resolve().parent.parent / "docs" / "formats.md"

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
    """Lowercased format names from a README or docs/formats.md table cell
    such as "DOCX, TXT, Markdown (`.md`)", "TXT, PDF/A-2b<sup>†</sup>" or
    "WebP, AVIF, BMP, TIFF, GIF, ICO, **PDF**" — footnote markup, bold
    markers and a note after the name are dropped."""
    cell = re.sub(r"<[^>]+>|†|\*", "", cell)
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


def _label_tokens(label: str) -> set[str]:
    """Formats in a first-column label of docs/formats.md: "TIFF / TIF" names
    one format twice, "M4A / AAC" two formats ("PDF/A-2b" is not split)."""
    return {fmt for spelling in re.split(r"\s+/\s+", label) for fmt in _cell_tokens(spelling)}


def _formats_md_conversions() -> dict[str, tuple[set[str], set[str]]]:
    """From label → (source formats, target formats) of the "| From | To | Notes |"
    tables in docs/formats.md. Rows sharing a label (DOCX → PDF, DOCX → TXT) are
    merged — those tables give each pair its own row and note."""
    text = FORMATS_MD.read_text(encoding="utf-8")
    tables = re.findall(r"\|\s*From\s*\|\s*To\s*\|\s*Notes\s*\|\n\|[-:| ]+\|\n((?:\|.*\n)+)", text)
    assert tables, "docs/formats.md: no '| From | To | Notes |' tables found"
    conversions: dict[str, tuple[set[str], set[str]]] = {}
    for first, to_cell in re.findall(r"^\|([^|]*)\|([^|]*)\|", "".join(tables), re.M):
        label = first.strip(" *")
        ins, outs = conversions.setdefault(label, (set(), set()))
        ins |= _label_tokens(label)
        outs |= _cell_tokens(to_cell)
    return conversions


def _formats_md_any_to_any() -> list[set[str]]:
    """Formats of each "| Format | Description |" table (Audio, Video) that is
    followed by "Any of the above can be converted to any other format." — the
    sentence is part of the pattern, so its claim is what gets tested."""
    text = FORMATS_MD.read_text(encoding="utf-8")
    tables = re.findall(
        r"\|\s*Format\s*\|\s*Description\s*\|.*\n\|[-:| ]+\|\n((?:\|.*\n)+)"
        r"\nAny of the above can be converted to any other format\.",
        text,
    )
    assert tables, "docs/formats.md: no format list followed by 'Any of the above …' found"
    return [
        {fmt for first in re.findall(r"^\|([^|]*)\|", table, re.M) for fmt in _label_tokens(first)}
        for table in tables
    ]


def test_formats_md_sources_match_registry():
    """Every format the registry converts from is documented — in a conversion
    table or an Audio/Video list. Catches a missing row (there was no ICO row)."""
    found = {fmt for ins, _ in _formats_md_conversions().values() for fmt in ins}
    found |= {fmt for group in _formats_md_any_to_any() for fmt in group}
    _assert_matches_registry(
        found,
        "docs/formats.md (conversion tables, plus Audio/Video lists followed by "
        "'Any of the above can be converted to any other format.')",
    )


def test_formats_md_conversion_targets_match_registry():
    """Each source named in a From label converts to exactly what the label's To
    cells list, minus the label's own format ("JPG / JPEG" doesn't list JPG,
    although jpg → jpeg is registered). All drift is reported at once."""
    conversions = get_public_conversions()
    drift: list[str] = []
    for label, (ins, outs) in _formats_md_conversions().items():
        for src in (s for s in conversions if _alias(s) in ins):
            expected = {_alias(tgt) for tgt in conversions[src]} - ins
            if outs != expected:
                drift.append(
                    f"  {label!r} ({src}) — missing: {sorted(expected - outs)}, "
                    f"extra: {sorted(outs - expected)}"
                )
    assert not drift, (
        "docs/formats.md conversion tables drifted from the converter registry:\n"
        + "\n".join(drift)
    )


def test_formats_md_any_to_any_lists_match_registry():
    """The claim under the Audio and Video lists — "any of the above can be
    converted to any other format" — holds for every format in them."""
    conversions = get_public_conversions()
    drift: list[str] = []
    for group in _formats_md_any_to_any():
        for fmt in sorted(group):
            actual = {_alias(tgt) for tgt in conversions.get(fmt, [])}
            expected = group - {fmt}
            if actual != expected:
                drift.append(
                    f"  {fmt!r} — missing: {sorted(expected - actual)}, "
                    f"extra: {sorted(actual - expected)}"
                )
    assert not drift, (
        "docs/formats.md: these formats don't convert to exactly the other formats "
        "of their Audio/Video list:\n" + "\n".join(drift)
    )


def test_enterprise_page_format_pair_claim_is_not_an_overclaim(client, monkeypatch):
    """enterprise.html claims "180+ format pairs" — counted from the same
    get_public_conversions() that /formats renders from, with spelling
    variants (jpg/jpeg, tif/tiff, htm/html, …) merged so they don't count
    twice. If the registry ever shrinks below 180 distinct pairs the claim
    becomes false; fail loudly here instead of overclaiming on a public page."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    distinct = {
        (_alias(src), _alias(tgt)) for src, tgts in get_public_conversions().items() for tgt in tgts
    }
    pairs = len({pair for pair in distinct if pair[0] != pair[1]})
    assert pairs >= 180, f"registry only has {pairs} distinct pairs — enterprise.html claims 180+"
    for path in ("/en/enterprise", "/de/enterprise"):
        assert "180+" in client.get(path).text, f"{path} lost its '180+ format pairs' claim"
