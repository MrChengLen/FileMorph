# SPDX-License-Identifier: AGPL-3.0-or-later
"""Page copy for the operations-first ``/tools`` hub.

Like ``pdf_tools_content.PDF_TOOL_CONTENT`` and ``convert_pairs.PAIR_CONTENT``,
the prose lives as plain bilingual data (``de`` / ``en``), not gettext — only
the page *chrome* (section headings, the cross-link to ``/formats``) is
translated via ``_()`` in the template. See
``docs-internal/ia-navigation-konzept.md`` for the IA rationale: this hub is
operations-first, as opposed to ``/formats``, the format-first reference
matrix.

The cards themselves come from the page catalogue (``app/core/catalog.py``):
one per tool page, under the tool's name and ``blurb``. This module holds only
the page's own copy. The ``intro`` points at the converter on the homepage,
the sole discoverability surface for multi-file batch conversion, a tool
*mode* with no URL of its own — so it deliberately names it (see the
Konsistenzregel: "Modi zählen nicht als eigene Operation").
"""

from __future__ import annotations

from app.core.i18n import normalize_locale

# Per-locale fields:
#   title      — SEO <title> sans the " | FileMorph" suffix (<=48 chars)
#   meta       — meta description (50-160 chars)
#   h1         — visible page heading
#   hero       — one-line sub-heading under the H1
#   intro      — the line pointing at the converter on the homepage
#   intro_link — the link text after it
TOOLS_CONTENT: dict[str, dict] = {
    "en": {
        "title": "File tools — convert, compress & PDF",
        "meta": (
            "Browse every FileMorph tool — convert & compress files, split, "
            "extract or insert PDF pages, or shrink a PDF to a target size. "
            "Free, no account needed."
        ),
        "h1": "All FileMorph tools",
        "hero": (
            "Every FileMorph tool in one place — convert or compress a file, "
            "or work with PDF pages. Pick one to get started."
        ),
        "intro": (
            "Another format, or several files at once? The converter on the "
            "homepage shows which formats your file can become, and converts "
            "several files at once (batch conversion)."
        ),
        "intro_link": "Open the converter →",
    },
    "de": {
        "title": "Tools — konvertieren, komprimieren, PDF",
        "meta": (
            "Alle FileMorph-Tools: Dateien konvertieren und komprimieren, "
            "PDF-Seiten aufteilen, extrahieren oder einfügen und PDFs "
            "verkleinern. Kostenlos und ohne Konto."
        ),
        "h1": "Alle FileMorph-Tools",
        "hero": (
            "Alle FileMorph-Tools an einem Ort — Dateien konvertieren oder "
            "komprimieren, oder mit PDF-Seiten arbeiten. Wähle ein Tool, um "
            "loszulegen."
        ),
        "intro": (
            "Ein anderes Format oder mehrere Dateien auf einmal? Der Konverter "
            "auf der Startseite zeigt, in welche Formate deine Datei umgewandelt "
            "werden kann, und wandelt mehrere Dateien auf einmal um "
            "(Stapelverarbeitung)."
        ),
        "intro_link": "Zum Konverter →",
    },
}


def get_tools_content(locale: str) -> dict:
    """Return the localized ``/tools`` hub content block."""
    return TOOLS_CONTENT[normalize_locale(locale)]
