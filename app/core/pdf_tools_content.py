# SPDX-License-Identifier: AGPL-3.0-or-later
"""Landing-page content for the three PDF structural-operation tools:
``/pdf/split``, ``/pdf/extract``, ``/pdf/compress``.

Like ``convert_pairs.PAIR_CONTENT`` and ``redact_content.REDACT_CONTENT``, the
prose lives as plain bilingual data (``de`` / ``en``), not gettext, so the
``.po`` catalogue only carries the page *chrome* (section headings) and the JS
runtime strings, translated via ``_()``. Three focused pages instead of one
generic "PDF tools" page because each targets a distinct search intent ("pdf
teilen" / "seiten extrahieren" / "pdf verkleinern").

Honesty is load-bearing here (project motto): every ``limits`` block states
the real constraint plainly — split's 10,000-page cap and ZIP output, extract's
1-based range syntax, and compress's "only raster images are recompressed;
a text-only PDF comes back unchanged and the tool says so" behaviour. No MB
figures are hardcoded, since caps are tier-configurable (see ``quotas.py``)
and would drift out of sync with this static content.
"""

from __future__ import annotations

from app.core.i18n import normalize_locale

# Per-locale fields:
#   title         — SEO <title> sans the " | FileMorph" suffix (<=48 chars)
#   meta          — meta description (50-160 chars)
#   h1 / hero     — visible heading + one-line sub-heading
#   cta           — submit-button label for this tool
#   limits        — honest limits paragraph (no hardcoded MB tier values)
#   how_it_works  — list of (step_label, step_text), 3 entries
#   when          — "when to use it" paragraph
#   faq           — list of (question, answer), 3 entries
PDF_TOOL_CONTENT: dict[str, dict[str, dict]] = {
    "split": {
        "en": {
            "title": "Split a PDF into pages online — free",
            "meta": (
                "Split a PDF into individual pages online for free, no account. Get a "
                "ZIP with one PDF per page. EU-hosted, files deleted right after."
            ),
            "h1": "Split a PDF into pages",
            "hero": "Turn a multi-page PDF into one file per page, bundled as a ZIP.",
            "cta": "Split PDF",
            "limits": (
                "Split returns a ZIP with one PDF per page — page_1.pdf, "
                "page_2.pdf, and so on (zero-padded for larger documents). "
                "A document is capped at 10,000 pages; "
                "anything larger is rejected before any processing starts, and the "
                "assembled ZIP must still fit your plan's output-size cap like any "
                "other download."
            ),
            "how_it_works": [
                (
                    "Upload your PDF",
                    "Upload the multi-page PDF you want to split — nothing changes on your device.",
                ),
                (
                    "Server splits every page",
                    "Each page becomes its own single-page PDF, named page_1.pdf, "
                    "page_2.pdf, and so on.",
                ),
                (
                    "Download the ZIP",
                    "Download one ZIP archive containing all the single-page PDFs.",
                ),
            ],
            "when": (
                "Use it when you need each page of a document as its own file — "
                "distributing individual invoice pages, archiving a scanned stack "
                "of receipts page by page, or feeding single pages into another "
                "tool that only accepts one page at a time."
            ),
            "faq": [
                (
                    "Can I split only some pages instead of all of them?",
                    "This tool splits every page into its own file. If you only "
                    "need a subset, use the page-extraction tool instead — it lets "
                    "you pick a page range and get back a single PDF.",
                ),
                (
                    "Is there a limit on how many pages I can split?",
                    "Yes — up to 10,000 pages. A larger document is rejected up "
                    "front with a clear error, rather than failing partway through.",
                ),
                (
                    "Do I need an account?",
                    "No — splitting works anonymously with no account. Registering "
                    "raises the size limits that apply to your upload and the "
                    "resulting ZIP.",
                ),
            ],
        },
        "de": {
            "title": "PDF in Einzelseiten aufteilen — kostenlos",
            "meta": (
                "PDF kostenlos online in Einzelseiten aufteilen, ohne Konto. Ein "
                "ZIP mit einem PDF pro Seite. EU-gehostet, Dateien sofort gelöscht."
            ),
            "h1": "PDF in Einzelseiten aufteilen",
            "hero": "Ein mehrseitiges PDF in einzelne Seiten aufteilen — als ZIP zum Download.",
            "cta": "PDF aufteilen",
            "limits": (
                "Beim Aufteilen erhältst du ein ZIP mit einem PDF pro Seite — "
                "page_1.pdf, page_2.pdf und so weiter (bei großen Dokumenten mit "
                "führenden Nullen). Ein Dokument ist auf "
                "10.000 Seiten begrenzt; alles Größere wird abgelehnt, bevor "
                "irgendetwas verarbeitet wird, und das fertige ZIP muss wie jeder "
                "andere Download innerhalb der Ausgabegrößen-Grenze deines Tarifs "
                "bleiben."
            ),
            "how_it_works": [
                (
                    "PDF hochladen",
                    "Lade das mehrseitige PDF hoch, das du aufteilen möchtest — auf "
                    "deinem Gerät ändert sich nichts.",
                ),
                (
                    "Server teilt jede Seite auf",
                    "Jede Seite wird zu einem eigenen einseitigen PDF, benannt "
                    "page_1.pdf, page_2.pdf und so weiter.",
                ),
                (
                    "ZIP herunterladen",
                    "Lade ein ZIP-Archiv mit allen einseitigen PDFs herunter.",
                ),
            ],
            "when": (
                "Nutze es, wenn du jede Seite eines Dokuments als eigene Datei "
                "brauchst — einzelne Rechnungsseiten verteilen, einen "
                "eingescannten Belegstapel Seite für Seite archivieren oder "
                "einzelne Seiten in ein anderes Tool einspeisen, das nur eine "
                "Seite auf einmal akzeptiert."
            ),
            "faq": [
                (
                    "Kann ich nur bestimmte Seiten aufteilen statt alle?",
                    "Dieses Tool teilt jede Seite in eine eigene Datei auf. "
                    "Brauchst du nur einen Teil, nutze stattdessen das "
                    "Tool zum Extrahieren von Seiten — dort wählst du einen "
                    "Seitenbereich und erhältst ein einzelnes PDF zurück.",
                ),
                (
                    "Gibt es ein Limit für die Seitenzahl?",
                    "Ja — bis zu 10.000 Seiten. Ein größeres Dokument wird sofort "
                    "mit einer klaren Fehlermeldung abgelehnt, statt mittendrin "
                    "fehlzuschlagen.",
                ),
                (
                    "Brauche ich ein Konto?",
                    "Nein — das Aufteilen funktioniert anonym ohne Konto. Eine "
                    "Registrierung hebt die Größengrenzen für Upload und das "
                    "entstehende ZIP an.",
                ),
            ],
        },
    },
    "extract": {
        "en": {
            "title": "Extract pages from a PDF online — free",
            "meta": (
                "Extract specific pages from a PDF online for free, no account. "
                "Enter a page range like 1-3,5 and download just those pages. "
                "EU-hosted."
            ),
            "h1": "Extract pages from a PDF",
            "hero": "Pick the pages you need and download them as a single, smaller PDF.",
            "cta": "Extract pages",
            "limits": (
                "Page numbers are 1-based and written like '1-3,5' (comma-separated "
                "numbers and ranges). A selection can resolve to at most 10,000 "
                "pages, and an empty, reversed (like '5-3'), or out-of-range "
                "selection is rejected with a clear message instead of a guessed "
                "result."
            ),
            "how_it_works": [
                (
                    "Upload your PDF",
                    "Upload the PDF you want to pull pages out of.",
                ),
                (
                    "Enter the pages you want",
                    "Type the page numbers or ranges to keep, e.g. 1-3,5 — "
                    "1-based, comma-separated.",
                ),
                (
                    "Download the result",
                    "Download a single PDF containing only the pages you "
                    "selected, in ascending order.",
                ),
            ],
            "when": (
                "Use it when you only need part of a PDF — pulling a signature "
                "page out of a contract, sharing just the relevant pages of a "
                "report, or submitting pages 2-4 of a longer form without "
                "sending the whole document."
            ),
            "faq": [
                (
                    "How do I write the page selection?",
                    "Comma-separated page numbers and ranges, 1-based — e.g. "
                    "'1-3,5' keeps pages 1, 2, 3 and 5. A reversed range like "
                    "'5-3', or a page number that doesn't exist in the document, "
                    "is rejected with a clear message.",
                ),
                (
                    "Does the page order in my input matter?",
                    "No — the result always comes back in ascending page order, "
                    "so '5,1-3' and '1-3,5' produce the identical PDF.",
                ),
                (
                    "Is there a limit on how many pages I can extract?",
                    "Yes — a selection can resolve to at most 10,000 pages.",
                ),
            ],
        },
        "de": {
            "title": "PDF-Seiten extrahieren — kostenlos",
            "meta": (
                "Bestimmte Seiten kostenlos online aus einem PDF extrahieren, ohne "
                "Konto. Seitenbereich wie 1-3,5 eingeben und nur diese Seiten "
                "herunterladen. EU-gehostet."
            ),
            "h1": "Seiten aus einem PDF extrahieren",
            "hero": "Wähle die Seiten, die du brauchst, und lade sie als kleineres PDF herunter.",
            "cta": "Seiten extrahieren",
            "limits": (
                "Seitenzahlen sind 1-basiert und werden wie '1-3,5' geschrieben "
                "(kommagetrennte Zahlen und Bereiche). Eine Auswahl darf höchstens "
                "10.000 Seiten ergeben; eine leere, umgekehrte (z. B. '5-3') oder "
                "außerhalb liegende Auswahl wird mit einer klaren Meldung "
                "abgelehnt, statt zu einem geratenen Ergebnis zu führen."
            ),
            "how_it_works": [
                (
                    "PDF hochladen",
                    "Lade das PDF hoch, aus dem du Seiten herausziehen möchtest.",
                ),
                (
                    "Gewünschte Seiten eingeben",
                    "Gib die zu behaltenden Seitenzahlen oder -bereiche ein, z. B. "
                    "1-3,5 — 1-basiert, kommagetrennt.",
                ),
                (
                    "Ergebnis herunterladen",
                    "Lade ein einzelnes PDF mit nur den ausgewählten Seiten in "
                    "aufsteigender Reihenfolge herunter.",
                ),
            ],
            "when": (
                "Nutze es, wenn du nur einen Teil eines PDFs brauchst — eine "
                "Unterschriftenseite aus einem Vertrag herausziehen, nur die "
                "relevanten Seiten eines Berichts teilen oder die Seiten 2-4 "
                "eines längeren Formulars einreichen, ohne das ganze Dokument zu "
                "verschicken."
            ),
            "faq": [
                (
                    "Wie schreibe ich die Seitenauswahl?",
                    "Kommagetrennte Seitenzahlen und -bereiche, 1-basiert — z. B. "
                    "behält '1-3,5' die Seiten 1, 2, 3 und 5. Ein umgekehrter "
                    "Bereich wie '5-3' oder eine im Dokument nicht existierende "
                    "Seite wird mit einer klaren Meldung abgelehnt.",
                ),
                (
                    "Spielt die Reihenfolge meiner Eingabe eine Rolle?",
                    "Nein — das Ergebnis kommt immer in aufsteigender "
                    "Seitenreihenfolge zurück, '5,1-3' und '1-3,5' ergeben also "
                    "dasselbe PDF.",
                ),
                (
                    "Gibt es ein Limit für die Anzahl extrahierbarer Seiten?",
                    "Ja — eine Auswahl darf höchstens 10.000 Seiten ergeben.",
                ),
            ],
        },
    },
    "compress": {
        "en": {
            "title": "Compress a PDF to a target size — free",
            "meta": (
                "Compress a PDF toward a target size online for free, no account. "
                "Recompresses embedded images; honestly reports when there's "
                "nothing to shrink. EU-hosted."
            ),
            "h1": "Compress a PDF to a target size",
            "hero": "Shrink a PDF toward a size you choose by recompressing its embedded images.",
            "cta": "Compress PDF",
            "limits": (
                "Only embedded raster images (photos, scans) are recompressed — "
                "text, fonts and vector graphics are left untouched. A text-only "
                "or already-optimized PDF has nothing to shrink, so it comes back "
                "valid and unchanged; the tool always shows the size it actually "
                "achieved and says plainly when the target wasn't reached, rather "
                "than pretending it worked."
            ),
            "how_it_works": [
                (
                    "Upload your PDF",
                    "Upload the PDF you want to shrink.",
                ),
                (
                    "Set a target size",
                    "Enter the size you're aiming for in MB — the engine "
                    "recompresses embedded images toward that budget.",
                ),
                (
                    "Download the result",
                    "Download the compressed PDF — the achieved size is shown, "
                    "along with a plain note if the target wasn't reached.",
                ),
            ],
            "when": (
                "Use it before emailing a scanned document that's too large, "
                "when an upload portal enforces a size limit, or to shrink an "
                "image-heavy archive of scanned PDFs before storing it."
            ),
            "faq": [
                (
                    "Will my PDF always hit the target size exactly?",
                    "Not always — only embedded raster images can be "
                    "recompressed, and some PDFs have little or nothing to "
                    "shrink. You always get the best achievable size back, with "
                    "a plain note about whether the target was reached.",
                ),
                (
                    "What happens if my PDF has no images to compress?",
                    "You get the original PDF back unchanged, with a note that "
                    "there was nothing to recompress — never a fake 'compressed' "
                    "file that's actually identical.",
                ),
                (
                    "Do I need an account?",
                    "No — anonymous use works for smaller files; a registered "
                    "plan raises the size limits.",
                ),
            ],
        },
        "de": {
            "title": "PDF auf Zielgröße verkleinern — kostenlos",
            "meta": (
                "PDF kostenlos online auf eine Zielgröße verkleinern, ohne Konto. "
                "Rekomprimiert Bilder, meldet ehrlich, wenn nichts zu verkleinern "
                "ist. EU-gehostet."
            ),
            "h1": "PDF auf eine Zielgröße verkleinern",
            "hero": (
                "Ein PDF durch Rekomprimieren eingebetteter Bilder auf eine "
                "gewünschte Größe verkleinern."
            ),
            "cta": "PDF verkleinern",
            "limits": (
                "Rekomprimiert werden nur eingebettete Rasterbilder (Fotos, "
                "Scans) — Text, Schriften und Vektorgrafiken bleiben "
                "unangetastet. Ein reines Text-PDF oder ein bereits optimiertes "
                "PDF hat nichts zu verkleinern und kommt darum gültig und "
                "unverändert zurück; das Tool zeigt immer die tatsächlich "
                "erreichte Größe und sagt offen, wenn das Ziel nicht erreicht "
                "wurde, statt einen Erfolg vorzutäuschen."
            ),
            "how_it_works": [
                (
                    "PDF hochladen",
                    "Lade das PDF hoch, das du verkleinern möchtest.",
                ),
                (
                    "Zielgröße festlegen",
                    "Gib die angestrebte Größe in MB ein — die Engine "
                    "komprimiert eingebettete Bilder in Richtung dieses Budgets "
                    "neu.",
                ),
                (
                    "Ergebnis herunterladen",
                    "Lade das komprimierte PDF herunter — die erreichte Größe "
                    "wird angezeigt, mit einem klaren Hinweis, falls das Ziel "
                    "nicht erreicht wurde.",
                ),
            ],
            "when": (
                "Nutze es, bevor du ein zu großes eingescanntes Dokument per "
                "E-Mail verschickst, wenn ein Upload-Portal ein Größenlimit "
                "durchsetzt, oder um ein bildlastiges Archiv gescannter PDFs "
                "vor der Speicherung zu verkleinern."
            ),
            "faq": [
                (
                    "Erreicht mein PDF immer genau die Zielgröße?",
                    "Nicht immer — nur eingebettete Rasterbilder lassen sich "
                    "rekomprimieren, manche PDFs haben wenig oder nichts zu "
                    "verkleinern. Du bekommst immer die bestmöglich erreichte "
                    "Größe zurück, mit einem klaren Hinweis, ob das Ziel "
                    "erreicht wurde.",
                ),
                (
                    "Was passiert, wenn mein PDF keine Bilder zum Komprimieren hat?",
                    "Du bekommst das ursprüngliche PDF unverändert zurück, mit "
                    "dem Hinweis, dass es nichts zu rekomprimieren gab — nie "
                    "eine vorgetäuschte 'komprimierte' Datei, die in Wirklichkeit "
                    "identisch ist.",
                ),
                (
                    "Brauche ich ein Konto?",
                    "Nein — anonyme Nutzung funktioniert für kleinere Dateien; "
                    "ein registrierter Tarif hebt die Größengrenzen an.",
                ),
            ],
        },
    },
}


def get_pdf_tool_content(tool: str, locale: str) -> dict | None:
    """Return the localized content block for ``tool``, or ``None`` if unknown.

    ``None`` is the route-level whitelist: ``/pdf/<tool>`` 404s for anything
    not curated here (e.g. ``/pdf/rotate``) rather than rendering a hollow page.
    """
    entry = PDF_TOOL_CONTENT.get(tool)
    if entry is None:
        return None
    return entry[normalize_locale(locale)]
