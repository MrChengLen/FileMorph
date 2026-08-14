# SPDX-License-Identifier: AGPL-3.0-or-later
"""Landing-page content for the operations-first ``/tools`` hub.

Like ``pdf_tools_content.PDF_TOOL_CONTENT`` and ``convert_pairs.PAIR_CONTENT``,
the prose lives as plain bilingual data (``de`` / ``en``), not gettext — only
the page *chrome* (section headings, the cross-link to ``/formats``) is
translated via ``_()`` in the template. See
``docs-internal/ia-navigation-konzept.md`` for the IA rationale: this hub is
operations-first (Convert & compress, PDF tools, Privacy tools) as opposed to
``/formats``, which is the format-first reference matrix.

The Convert & Compress card is the sole discoverability surface for
multi-file batch conversion, a tool *mode* with no URL of its own — its
``desc`` deliberately names it (see the Konsistenzregel: "Modi zählen nicht
als eigene Operation"). Compress-to-an-exact-target-size *did* live under
that same rule until IA rework PR 4 gave it a dedicated page, ``/compress``
— it now has its own "Compress to a target size" card right next to this
one instead. Video is deliberately not claimed here for exact-target
sizing: ``app/compressors/video.py`` only supports quality-based
compression (no ``target_bytes``), and the client-side
``TARGET_SIZE_FORMATS`` gate in ``app/static/js/app.js`` never offers
target-size mode for a video file — see ``compress_content.py`` for the
full claims audit.

The Redact card is a commercial Cloud-Edition add-on (see ``redact_content``);
its title carries a plain-text "(Pro)" suffix — no badge styling — and the
route/template gate the whole card on ``ai_operations_enabled`` so a
self-host build never renders it.
"""

from __future__ import annotations

from app.core.i18n import normalize_locale

# Per-locale fields:
#   title  — SEO <title> sans the " | FileMorph" suffix (<=48 chars)
#   meta   — meta description (50-160 chars)
#   h1     — visible page heading
#   hero   — one-line sub-heading under the H1
#   cards  — {card_key: {"title": ..., "desc": ...}}, 1-2 sentences each
TOOLS_CONTENT: dict[str, dict] = {
    "en": {
        "title": "File tools — convert, compress & PDF",
        "meta": (
            "Browse every FileMorph tool — convert & compress files, split or "
            "extract PDF pages, or shrink a PDF to a target size. Free, no "
            "account, EU-hosted."
        ),
        "h1": "All FileMorph tools",
        "hero": (
            "Every FileMorph tool in one place — convert or compress a file, "
            "or work with PDF pages. Pick one to get started."
        ),
        "cards": {
            "convert": {
                "title": "Convert & compress files",
                "desc": (
                    "The main tool — convert between formats, or compress a "
                    "file. Drop in several files at once for batch conversion."
                ),
            },
            "compress_target": {
                "title": "Compress to a target size",
                "desc": (
                    "Dial in an exact target size in MB for a JPEG or WebP "
                    "image, or shrink a video by quality — the dedicated "
                    "tool, with honest limits on which formats hit a target."
                ),
            },
            "split": {
                "title": "Split a PDF",
                "desc": "Turn a multi-page PDF into one file per page, bundled as a ZIP.",
            },
            "extract": {
                "title": "Extract PDF pages",
                "desc": (
                    "Keep only the pages you choose, e.g. 1-3,5, and download a single smaller PDF."
                ),
            },
            "compress": {
                "title": "Compress a PDF",
                "desc": (
                    "Shrink a PDF toward a target size by recompressing its "
                    "embedded images — and get an honest note if there's "
                    "nothing to shrink."
                ),
            },
            "redact": {
                "title": "Redact PII (Pro)",
                "desc": (
                    "Find and remove IBANs, emails, phone numbers, IP "
                    "addresses and credit-card numbers from TXT, DOCX and "
                    "XLSX. Free findings preview, paid file download."
                ),
            },
        },
    },
    "de": {
        "title": "Tools — konvertieren, komprimieren, PDF",
        "meta": (
            "Alle FileMorph-Tools: Dateien konvertieren und komprimieren, "
            "PDF-Seiten aufteilen, extrahieren oder verkleinern. Kostenlos, "
            "ohne Konto, EU-gehostet."
        ),
        "h1": "Alle FileMorph-Tools",
        "hero": (
            "Alle FileMorph-Tools an einem Ort — Dateien konvertieren oder "
            "komprimieren, oder mit PDF-Seiten arbeiten. Wähle ein Tool, um "
            "loszulegen."
        ),
        "cards": {
            "convert": {
                "title": "Dateien konvertieren & komprimieren",
                "desc": (
                    "Das Haupt-Tool — wandle zwischen Formaten um oder "
                    "komprimiere eine Datei. Lade mehrere Dateien gleichzeitig "
                    "hoch für die Stapelverarbeitung."
                ),
            },
            "compress_target": {
                "title": "Auf Zielgröße komprimieren",
                "desc": (
                    "Für ein JPEG oder WebP eine exakte Größe in MB "
                    "einstellen, oder ein Video per Qualität verkleinern — "
                    "das eigene Tool, mit ehrlichem Hinweis, welche Formate "
                    "eine exakte Zielgröße erreichen."
                ),
            },
            "split": {
                "title": "PDF aufteilen",
                "desc": ("Ein mehrseitiges PDF in Einzelseiten aufteilen, gebündelt als ZIP."),
            },
            "extract": {
                "title": "PDF-Seiten extrahieren",
                "desc": (
                    "Nur die gewünschten Seiten behalten, z. B. 1-3,5, und ein "
                    "einzelnes kleineres PDF herunterladen."
                ),
            },
            "compress": {
                "title": "PDF verkleinern",
                "desc": (
                    "Ein PDF durch Rekomprimieren eingebetteter Bilder auf "
                    "eine Zielgröße verkleinern — mit ehrlichem Hinweis, wenn "
                    "nichts zu verkleinern ist."
                ),
            },
            "redact": {
                "title": "PII redigieren (Pro)",
                "desc": (
                    "IBANs, E-Mail-Adressen, Telefonnummern, IP-Adressen und "
                    "Kartennummern in TXT, DOCX und XLSX finden und entfernen. "
                    "Kostenlose Fundstellen-Vorschau, Download kostenpflichtig."
                ),
            },
        },
    },
}


def get_tools_content(locale: str) -> dict:
    """Return the localized ``/tools`` hub content block."""
    return TOOLS_CONTENT[normalize_locale(locale)]
