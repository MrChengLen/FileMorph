# SPDX-License-Identifier: AGPL-3.0-or-later
"""Landing-page content for ``/compress`` — the image/video target-size
compression tool (IA rework PR 4, ``docs-internal/ia-navigation-konzept.md``).

Like ``pdf_tools_content.PDF_TOOL_CONTENT`` and ``tools_content.TOOLS_CONTENT``,
the prose lives as plain bilingual data (``de`` / ``en``), not gettext — only
the page *chrome* (section headings) is translated via ``_()`` in the template.
Shape mirrors ``tools_content`` (one page, keyed only by locale) with the
richer field set of ``pdf_tools_content`` (limits / how_it_works / when / faq).

Claims discipline (project motto: honesty over marketing): every numeric or
format claim below is verified against the actual compress code before being
stated, not assumed from the product's own marketing copy elsewhere:

- Target-size compression (binary search on quality, accepting the first
  result within the ``tolerance=0.03`` default of
  ``compress_image_to_target()`` — so up to 3 % *above* the target) only
  exists for JPEG/WebP/AVIF — see ``TARGET_SIZE_FORMATS`` in
  ``app/compressors/image.py`` *and* the ``TARGET_SIZE_FORMATS`` JS constant
  in ``app/static/js/app.js`` that actually gates the UI; the two sets are
  pinned equal by ``tests/test_target_size_formats_parity.py``. AVIF's encode
  cost is stated plainly (a large photo can take a minute or more — measured
  locally ~30 s for a 12 MP photo on 2 cores, 2026-09), matching the UI's
  own hint.
- Video (``app/compressors/video.py::compress_video``) takes only a
  ``quality`` re-encode (CRF mapping) — there is no ``target_bytes``
  parameter, and ``/api/v1/compress`` 415s a video upload that sets
  ``target_size_kb``. So video compression is never described as hitting a
  target size here, only "by quality".
- The page runs on the server (``/api/v1/compress``), so it never says
  "in your browser", and it makes no hosting claim of its own — where the
  server runs is said once, in ``partials/hosting_note.html``.
- The "achieved size shown next to the download" honesty note is scoped to
  target-size mode only — ``app.js``'s ``download-link-label`` only gets the
  "(X.XX MB)" suffix when ``X-FileMorph-Achieved-Bytes`` is present, which
  the server only sets when ``target_size_kb`` was used.
"""

from __future__ import annotations

from app.core.i18n import normalize_locale

# Per-locale fields:
#   title         — SEO <title> sans the " | FileMorph" suffix (<=48 chars)
#   meta          — meta description (50-160 chars)
#   h1 / hero     — visible heading + one-line sub-heading
#   limits        — honest limits paragraph (no hardcoded MB tier values)
#   how_it_works  — list of (step_label, step_text), 3 entries
#   when          — "when to use it" paragraph
#   faq           — list of (question, answer), 3 entries
COMPRESS_CONTENT: dict[str, dict] = {
    "en": {
        "title": "Compress JPEG/WebP/AVIF to a target size — free",
        "meta": (
            "Shrink a JPG, WebP or AVIF image to a target size in MB, or compress "
            "a video — free, no account, files deleted right after."
        ),
        "h1": "Compress an image or video — target size for JPEG/WebP/AVIF",
        "hero": (
            "Dial in a size in MB for JPEG, WebP and AVIF, or shrink a "
            "video by quality — free, no account."
        ),
        "limits": (
            "Target-size compression — pick a size in MB and the engine "
            "binary-searches quality for a result close to it — works for "
            "JPEG, WebP and AVIF images only. The result can end up to 3 % "
            "above the target (a 5 MB target can give up to 5.15 MB), so leave "
            "a little room below a hard upload limit; if even the lowest quality "
            "is too big, you get the smallest version possible. The achieved "
            "size is shown next to the download. AVIF takes noticeably longer: "
            "its encoder is CPU-heavy and the search re-encodes several times, so a large "
            "photo can take a minute or more. PNG, TIFF and video don't take a "
            "target size: they compress by quality instead, where a lower "
            "number gives a smaller but lower-fidelity file."
        ),
        "how_it_works": [
            (
                "Upload your image or video",
                "Drop in a JPG, PNG, WebP, AVIF, TIFF or video file — Compress "
                "mode is already selected.",
            ),
            (
                "Pick a size or a quality",
                "For JPEG, WebP or AVIF, switch to “By target size” and enter a "
                "size in MB. Everything else uses the quality slider instead — "
                "lower is smaller.",
            ),
            (
                "Download the result",
                "In target-size mode, the achieved size appears right on the "
                "download button; in quality mode, just download the "
                "compressed file.",
            ),
        ],
        "when": (
            "Use it before emailing a photo that's over your provider's "
            "attachment limit, when an upload portal caps file size, or "
            "before sending a video through a messaging app with its own "
            "size limit."
        ),
        "faq": [
            (
                "Which files can I compress to a target size?",
                "Target-size compression currently works for JPEG, WebP "
                "and AVIF images — the engine binary-searches quality until the "
                "output is close to your target; it can end up to 3 % above it, or "
                "larger if the image can't get that small (AVIF takes noticeably "
                "longer). PNG and "
                "TIFF images, and every video format, use quality-based "
                "compression instead: there's no byte-exact target, just a "
                "slider between smaller and higher-fidelity.",
            ),
            (
                "I need to compress a PDF — is that here too?",
                "No — PDF compression works differently (it recompresses the "
                "images embedded inside the document, not a whole-file "
                "re-encode), so it has its own dedicated tool. Use Compress "
                "a PDF instead.",
            ),
            (
                "Do I need an account?",
                "No — anonymous use works for smaller files; a registered "
                "plan raises the size limits.",
            ),
        ],
    },
    "de": {
        "title": "JPG/WebP/AVIF auf Zielgröße verkleinern — gratis",
        "meta": (
            "Verkleinere ein JPG, WebP oder AVIF auf eine Zielgröße in "
            "MB, oder komprimiere ein Video — kostenlos, ohne Konto, "
            "Dateien sofort gelöscht."
        ),
        "h1": "Bild oder Video verkleinern — Zielgröße für JPEG/WebP/AVIF",
        "hero": (
            "Für JPEG, WebP und AVIF eine Größe in MB einstellen, "
            "oder ein Video per Qualität verkleinern — kostenlos, ohne "
            "Konto."
        ),
        "limits": (
            "Die Zielgrößen-Kompression — du gibst eine "
            "Größe in MB vor, die Engine sucht per Binärsuche eine "
            "Qualität mit einem Ergebnis nahe am Ziel — funktioniert nur "
            "für JPEG-, WebP- und AVIF-Bilder. Das Ergebnis kann bis zu 3 % "
            "über dem Ziel liegen (aus 5 MB werden bis zu 5,15 MB); lass "
            "unter einer harten Upload-Grenze also etwas Luft. Reicht selbst "
            "die niedrigste Qualität nicht, bekommst du die kleinstmögliche "
            "Fassung. Die erreichte Größe wird "
            "direkt neben dem Download angezeigt. AVIF dauert deutlich "
            "länger: Der Encoder ist rechenintensiv und die Suche kodiert "
            "mehrmals neu, daher kann ein großes Foto eine Minute oder "
            "länger brauchen. PNG, TIFF und Video nehmen "
            "keine Zielgröße entgegen: Sie werden stattdessen per "
            "Qualitätsregler komprimiert — ein niedrigerer Wert ergibt "
            "eine kleinere, aber weniger originalgetreue Datei."
        ),
        "how_it_works": [
            (
                "Bild oder Video hochladen",
                "Lade ein JPG, PNG, WebP, AVIF, TIFF oder eine Videodatei "
                "hoch — der Kompressions-Modus ist bereits ausgewählt.",
            ),
            (
                "Größe oder Qualität wählen",
                "Bei JPEG, WebP oder AVIF zu „Nach Zielgröße“ wechseln und "
                "eine Größe in MB eingeben. Alles andere nutzt den "
                "Qualitätsregler — niedriger bedeutet kleiner.",
            ),
            (
                "Ergebnis herunterladen",
                "Im Zielgrößen-Modus wird die erreichte Größe "
                "direkt am Download-Button angezeigt; im Qualitätsmodus "
                "einfach herunterladen und prüfen.",
            ),
        ],
        "when": (
            "Nutze es, bevor du ein Foto verschickst, das über dem "
            "Anhang-Limit deines E-Mail-Anbieters liegt, wenn ein "
            "Upload-Portal die Dateigröße begrenzt, oder bevor du ein "
            "Video über einen Messenger mit eigenem Größenlimit "
            "verschickst."
        ),
        "faq": [
            (
                "Welche Dateien kann ich auf eine Zielgröße komprimieren?",
                "Die Zielgrößen-Kompression funktioniert aktuell "
                "nur für JPEG-, WebP- und AVIF-Bilder — die Engine sucht per "
                "Binärsuche eine Qualität, bis das Ergebnis nahe am Ziel liegt; es "
                "kann bis zu 3 % darüber liegen, oder mehr, wenn das Bild nicht so "
                "klein wird (AVIF dauert deutlich länger). "
                "PNG- und TIFF-Bilder sowie alle "
                "Videoformate werden stattdessen per Qualität komprimiert: "
                "kein exaktes Byte-Ziel, nur ein Regler zwischen kleiner und "
                "originalgetreuer.",
            ),
            (
                "Ich will ein PDF komprimieren — geht das hier auch?",
                "Nein — PDF-Kompression funktioniert anders (sie "
                "rekomprimiert die im Dokument eingebetteten Bilder, nicht "
                "die ganze Datei neu) und hat deshalb ein eigenes Tool. Nutze "
                "stattdessen PDF verkleinern.",
            ),
            (
                "Brauche ich ein Konto?",
                "Nein — anonyme Nutzung funktioniert für kleinere "
                "Dateien; ein registrierter Tarif hebt die Größengrenzen "
                "an.",
            ),
        ],
    },
}


def get_compress_content(locale: str) -> dict:
    """Return the localized ``/compress`` content block."""
    return COMPRESS_CONTENT[normalize_locale(locale)]
