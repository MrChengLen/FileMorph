# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-format-pair landing-page content (Phase 2).

Each curated pair gets a real, hand-written, bilingual content block — NOT a
template with the format names swapped in. That distinction is deliberate:
Google's 2026 core updates penalise "scaled content abuse" (templated pages),
but reward pages that pair a genuinely useful tool with unique content. So the
``/convert/<src>-to-<tgt>`` route only serves a page when an entry exists here
(no entry → 404), which structurally prevents thin auto-generated pages.

Content lives as plain bilingual data (``de`` / ``en``), not gettext, to keep
the ``.po`` catalogue manageable — the page *chrome* (section headings) is
translated via ``_()`` in the template. Start small (a curated batch); measure
in Search Console before scaling, per docs-internal/seo-geo-strategie-2026.md.
"""

from __future__ import annotations

from app.core.i18n import normalize_locale

# Pretty display label per format (casing the bare extension can't give us).
_DISPLAY: dict[str, str] = {
    "jpg": "JPG",
    "jpeg": "JPEG",
    "png": "PNG",
    "webp": "WebP",
    "heic": "HEIC",
    "heif": "HEIF",
    "gif": "GIF",
    "bmp": "BMP",
    "tiff": "TIFF",
    "pdf": "PDF",
    "docx": "DOCX",
    "html": "HTML",
    "eml": "EML",
}


def format_label(fmt: str) -> str:
    return _DISPLAY.get(fmt.lower(), fmt.upper())


# Each entry: {(src, tgt): {"de": {...}, "en": {...}}}. Per-locale fields:
#   title  — SEO <title> sans the " | FileMorph" suffix (<=48 chars)
#   meta   — meta description (<=160 chars)
#   h1     — visible page heading
#   hero   — one-line sub-heading under the H1
#   when   — "when to use" paragraph (2-3 sentences, real intent)
#   tech   — technical facts: sizes, lossy/lossless, amplification, privacy
#   faq    — list of (question, answer) — 3 entries
PAIR_CONTENT: dict[tuple[str, str], dict[str, dict]] = {
    ("heic", "jpg"): {
        "en": {
            "title": "Convert HEIC to JPG online — free",
            "meta": "Convert iPhone HEIC photos to JPG online for free, no account. Universal compatibility for sharing and editing. Files deleted right after conversion, EU-hosted.",
            "h1": "Convert HEIC to JPG",
            "hero": "Turn iPhone & Apple HEIC photos into universally compatible JPG.",
            "when": "HEIC is Apple's efficient default photo format, but many websites, Windows apps and older programs can't open it. Convert to JPG when you need a photo that opens everywhere — for uploads, email attachments or editing in software that rejects HEIC.",
            "tech": "Both formats are lossy, so JPG keeps the visible quality while staying widely supported; expect the JPG to be roughly 1.5–2× the HEIC file size, since HEIC compresses more efficiently. Camera metadata (EXIF/GPS) is stripped during conversion, and files are processed server-side and deleted immediately.",
            "faq": [
                (
                    "Will the quality drop?",
                    "JPG is re-encoded at high quality, so the difference is visually negligible for normal viewing and printing. There's no way to add detail back, but nothing extra is lost beyond a single high-quality re-save.",
                ),
                (
                    "Why is the JPG bigger than the HEIC?",
                    "HEIC uses newer, more efficient compression than JPG, so the same photo takes more space as a JPG. That's the trade-off for JPG's universal compatibility.",
                ),
                (
                    "Do I need an account?",
                    "No. HEIC→JPG is free with no account, and your photo is deleted right after conversion.",
                ),
            ],
        },
        "de": {
            "title": "HEIC in JPG umwandeln — kostenlos",
            "meta": "iPhone-HEIC-Fotos kostenlos online in JPG umwandeln, ohne Konto. Universell kompatibel zum Teilen und Bearbeiten. Dateien sofort gelöscht, EU-gehostet.",
            "h1": "HEIC in JPG umwandeln",
            "hero": "iPhone- & Apple-HEIC-Fotos in universell kompatibles JPG umwandeln.",
            "when": "HEIC ist Apples effizientes Standard-Fotoformat, aber viele Websites, Windows-Programme und ältere Software können es nicht öffnen. Wandle in JPG um, wenn du ein Foto brauchst, das überall funktioniert — für Uploads, E-Mail-Anhänge oder die Bearbeitung in Programmen, die HEIC ablehnen.",
            "tech": "Beide Formate sind verlustbehaftet, JPG behält also die sichtbare Qualität bei voller Kompatibilität; das JPG wird etwa 1,5–2× so groß wie das HEIC, weil HEIC effizienter komprimiert. Kamera-Metadaten (EXIF/GPS) werden beim Umwandeln entfernt, die Datei serverseitig verarbeitet und sofort gelöscht.",
            "faq": [
                (
                    "Sinkt die Qualität?",
                    "JPG wird in hoher Qualität neu kodiert — der Unterschied ist beim normalen Betrachten und Drucken praktisch nicht sichtbar. Verlorenes Detail lässt sich nicht zurückholen, aber außer einem hochwertigen Neuspeichern geht nichts verloren.",
                ),
                (
                    "Warum ist das JPG größer als das HEIC?",
                    "HEIC komprimiert moderner und effizienter als JPG, dasselbe Foto braucht als JPG also mehr Platz. Das ist der Preis für die universelle Kompatibilität von JPG.",
                ),
                (
                    "Brauche ich ein Konto?",
                    "Nein. HEIC→JPG ist kostenlos und ohne Konto, und dein Foto wird direkt nach der Umwandlung gelöscht.",
                ),
            ],
        },
    },
    ("jpg", "pdf"): {
        "en": {
            "title": "Convert JPG to PDF online — free",
            "meta": "Convert JPG images to PDF online for free, no account. Turn photos and scans into a tidy PDF document. Files deleted right after conversion, EU-hosted.",
            "h1": "Convert JPG to PDF",
            "hero": "Turn a JPG photo or scan into a single-page PDF document.",
            "when": "Convert JPG to PDF when you need to submit a photo or scan as a document — for forms, applications, receipts or archiving. PDF opens identically on every device and is the expected format for official paperwork.",
            "tech": "The image becomes a single-page PDF at 150 DPI; transparency isn't a factor for JPG, and EXIF/GPS metadata is stripped. The PDF is usually a little larger than the JPG because of the PDF container, but quality is preserved. Everything runs server-side and the file is deleted right after.",
            "faq": [
                (
                    "Can I combine several JPGs into one PDF?",
                    "This page converts one image to a one-page PDF. Multi-image merging into a single PDF is on the roadmap — for now, convert each and combine with any PDF tool.",
                ),
                (
                    "Is the image quality kept?",
                    "Yes — the JPG is embedded into the PDF without a second lossy re-compression, so it looks the same as the original.",
                ),
                (
                    "Do I need to sign up?",
                    "No. JPG→PDF is free and account-free, and your file is deleted immediately after conversion.",
                ),
            ],
        },
        "de": {
            "title": "JPG in PDF umwandeln — kostenlos",
            "meta": "JPG-Bilder kostenlos online in PDF umwandeln, ohne Konto. Fotos und Scans in ein sauberes PDF-Dokument verwandeln. Dateien sofort gelöscht, EU-gehostet.",
            "h1": "JPG in PDF umwandeln",
            "hero": "Ein JPG-Foto oder einen Scan in ein einseitiges PDF-Dokument umwandeln.",
            "when": "Wandle JPG in PDF um, wenn du ein Foto oder einen Scan als Dokument einreichen musst — für Formulare, Anträge, Belege oder die Archivierung. PDF öffnet sich auf jedem Gerät gleich und ist das erwartete Format für offizielle Unterlagen.",
            "tech": "Das Bild wird zu einem einseitigen PDF mit 150 DPI; Transparenz spielt bei JPG keine Rolle, und EXIF/GPS-Metadaten werden entfernt. Das PDF ist durch den PDF-Container meist etwas größer als das JPG, die Qualität bleibt aber erhalten. Alles läuft serverseitig, die Datei wird direkt danach gelöscht.",
            "faq": [
                (
                    "Kann ich mehrere JPGs in ein PDF zusammenfassen?",
                    "Diese Seite wandelt ein Bild in ein einseitiges PDF um. Das Zusammenführen mehrerer Bilder in ein PDF ist geplant — wandle vorerst jedes einzeln um und füge sie mit einem beliebigen PDF-Tool zusammen.",
                ),
                (
                    "Bleibt die Bildqualität erhalten?",
                    "Ja — das JPG wird ohne zweite verlustbehaftete Kompression ins PDF eingebettet und sieht aus wie das Original.",
                ),
                (
                    "Muss ich mich registrieren?",
                    "Nein. JPG→PDF ist kostenlos und ohne Konto, und deine Datei wird sofort nach der Umwandlung gelöscht.",
                ),
            ],
        },
    },
    ("png", "pdf"): {
        "en": {
            "title": "Convert PNG to PDF online — free",
            "meta": "Convert PNG images to PDF online for free, no account. Ideal for screenshots, diagrams and logos. Files deleted right after conversion, EU-hosted, open source.",
            "h1": "Convert PNG to PDF",
            "hero": "Turn a PNG screenshot, diagram or logo into a PDF document.",
            "when": "Convert PNG to PDF when you want to share a screenshot, diagram or logo as a clean, printable document that looks the same everywhere. PDF is ideal for attaching crisp graphics to emails or submitting them as paperwork.",
            "tech": "The PNG becomes a single-page PDF; any transparency is flattened onto a white background since PDF has no alpha channel. PNG is lossless, so nothing is degraded, but the PDF can be sizeable for large screenshots. Processing is server-side with immediate deletion.",
            "faq": [
                (
                    "What happens to PNG transparency?",
                    "Transparent areas are placed on a white background, because PDF pages don't support an alpha channel. The visible content is unchanged.",
                ),
                (
                    "Is quality lost?",
                    "No. PNG is lossless and it's embedded into the PDF without re-compression, so it stays pixel-perfect.",
                ),
                (
                    "Is it really free?",
                    "Yes — no account, no watermark, and the file is deleted right after conversion.",
                ),
            ],
        },
        "de": {
            "title": "PNG in PDF umwandeln — kostenlos",
            "meta": "PNG-Bilder kostenlos online in PDF umwandeln, ohne Konto. Ideal für Screenshots, Diagramme und Logos. Dateien sofort gelöscht, EU-gehostet, Open Source.",
            "h1": "PNG in PDF umwandeln",
            "hero": "Einen PNG-Screenshot, ein Diagramm oder Logo in ein PDF-Dokument umwandeln.",
            "when": "Wandle PNG in PDF um, wenn du einen Screenshot, ein Diagramm oder Logo als sauberes, druckbares Dokument teilen willst, das überall gleich aussieht. PDF eignet sich ideal, um gestochen scharfe Grafiken an E-Mails zu hängen oder als Unterlage einzureichen.",
            "tech": "Das PNG wird zu einem einseitigen PDF; Transparenz wird auf weißen Hintergrund gelegt, da PDF keinen Alphakanal hat. PNG ist verlustfrei, es wird also nichts verschlechtert, das PDF kann bei großen Screenshots aber umfangreich werden. Die Verarbeitung läuft serverseitig mit sofortiger Löschung.",
            "faq": [
                (
                    "Was passiert mit der PNG-Transparenz?",
                    "Transparente Bereiche werden auf weißen Hintergrund gelegt, da PDF-Seiten keinen Alphakanal unterstützen. Der sichtbare Inhalt bleibt unverändert.",
                ),
                (
                    "Geht Qualität verloren?",
                    "Nein. PNG ist verlustfrei und wird ohne Neukompression ins PDF eingebettet, bleibt also pixelgenau.",
                ),
                (
                    "Ist es wirklich kostenlos?",
                    "Ja — kein Konto, kein Wasserzeichen, und die Datei wird direkt nach der Umwandlung gelöscht.",
                ),
            ],
        },
    },
    ("heic", "pdf"): {
        "en": {
            "title": "Convert HEIC to PDF online — free",
            "meta": "Convert iPhone HEIC photos to PDF online for free, no account. Submit photos as documents without the HEIC→JPG detour. Files deleted right after, EU-hosted.",
            "h1": "Convert HEIC to PDF",
            "hero": "Turn an iPhone HEIC photo straight into a PDF document.",
            "when": "Convert HEIC to PDF when you need to submit an iPhone photo as a document — a receipt, an ID scan, a form — without first converting to JPG. PDF is what most upload portals and offices expect.",
            "tech": "The HEIC is decoded and placed into a single-page PDF at 150 DPI; EXIF/GPS metadata is stripped in the process. The PDF is typically larger than the original HEIC because of both PDF packaging and HEIC's efficient compression. Files are processed server-side and deleted immediately.",
            "faq": [
                (
                    "Why convert HEIC straight to PDF?",
                    "It saves a step — no HEIC→JPG→PDF detour. You upload the iPhone photo and get a ready-to-submit PDF.",
                ),
                (
                    "Is anything lost?",
                    "The photo is embedded at high quality; only camera metadata is removed for privacy. There's no visible quality loss.",
                ),
                (
                    "Does it cost anything?",
                    "No. It's free, no account, and your photo is deleted right after conversion.",
                ),
            ],
        },
        "de": {
            "title": "HEIC in PDF umwandeln — kostenlos",
            "meta": "iPhone-HEIC-Fotos kostenlos online in PDF umwandeln, ohne Konto. Fotos als Dokument einreichen — ohne Umweg über JPG. Dateien sofort gelöscht, EU-gehostet.",
            "h1": "HEIC in PDF umwandeln",
            "hero": "Ein iPhone-HEIC-Foto direkt in ein PDF-Dokument umwandeln.",
            "when": "Wandle HEIC in PDF um, wenn du ein iPhone-Foto als Dokument einreichen musst — einen Beleg, einen Ausweis-Scan, ein Formular — ohne den Umweg über JPG. PDF erwarten die meisten Upload-Portale und Behörden.",
            "tech": "Das HEIC wird dekodiert und als einseitiges PDF mit 150 DPI eingebettet; EXIF/GPS-Metadaten werden dabei entfernt. Das PDF ist meist größer als das ursprüngliche HEIC — wegen der PDF-Verpackung und HEICs effizienter Kompression. Dateien werden serverseitig verarbeitet und sofort gelöscht.",
            "faq": [
                (
                    "Warum HEIC direkt in PDF?",
                    "Es spart einen Schritt — kein Umweg HEIC→JPG→PDF. Du lädst das iPhone-Foto hoch und erhältst ein fertig einreichbares PDF.",
                ),
                (
                    "Geht etwas verloren?",
                    "Das Foto wird in hoher Qualität eingebettet; nur Kamera-Metadaten werden aus Datenschutzgründen entfernt. Sichtbar geht keine Qualität verloren.",
                ),
                (
                    "Kostet das etwas?",
                    "Nein. Kostenlos, ohne Konto, und dein Foto wird direkt nach der Umwandlung gelöscht.",
                ),
            ],
        },
    },
    ("png", "jpg"): {
        "en": {
            "title": "Convert PNG to JPG online — free",
            "meta": "Convert PNG to JPG online for free, no account. Shrink screenshots and photos for web and email. Files deleted right after conversion, EU-hosted, open source.",
            "h1": "Convert PNG to JPG",
            "hero": "Shrink a PNG into a smaller, widely compatible JPG.",
            "when": "Convert PNG to JPG when file size matters more than transparency — photos and screenshots for email, web pages or uploads with size limits. JPG's lossy compression makes the file far smaller.",
            "tech": "PNG is lossless (large); JPG is lossy and typically 3–10× smaller for photographic content. Transparency is flattened onto white, since JPG has no alpha channel. The conversion strips metadata and runs server-side with immediate deletion.",
            "faq": [
                (
                    "How much smaller will it get?",
                    "For photos, often 3–10× smaller. For flat graphics with few colours, the saving is smaller and PNG may even be better — JPG suits photographic content.",
                ),
                (
                    "I lose transparency — why?",
                    "JPG has no alpha channel, so transparent areas become white. If you need transparency, convert to WebP instead.",
                ),
                (
                    "Is it free?",
                    "Yes — no account, and the file is deleted right after conversion.",
                ),
            ],
        },
        "de": {
            "title": "PNG in JPG umwandeln — kostenlos",
            "meta": "PNG kostenlos online in JPG umwandeln, ohne Konto. Screenshots und Fotos für Web und E-Mail verkleinern. Dateien sofort gelöscht, EU-gehostet, Open Source.",
            "h1": "PNG in JPG umwandeln",
            "hero": "Ein PNG in ein kleineres, breit kompatibles JPG verkleinern.",
            "when": "Wandle PNG in JPG um, wenn die Dateigröße wichtiger ist als Transparenz — Fotos und Screenshots für E-Mail, Webseiten oder Uploads mit Größenlimit. Die verlustbehaftete JPG-Kompression macht die Datei deutlich kleiner.",
            "tech": "PNG ist verlustfrei (groß); JPG ist verlustbehaftet und bei Fotos typisch 3–10× kleiner. Transparenz wird auf weiß gelegt, da JPG keinen Alphakanal hat. Die Umwandlung entfernt Metadaten und läuft serverseitig mit sofortiger Löschung.",
            "faq": [
                (
                    "Wie viel kleiner wird es?",
                    "Bei Fotos oft 3–10× kleiner. Bei flächigen Grafiken mit wenig Farben ist die Ersparnis kleiner und PNG ggf. sogar besser — JPG eignet sich für fotografische Inhalte.",
                ),
                (
                    "Ich verliere Transparenz — warum?",
                    "JPG hat keinen Alphakanal, transparente Bereiche werden also weiß. Wenn du Transparenz brauchst, wandle stattdessen in WebP um.",
                ),
                (
                    "Ist es kostenlos?",
                    "Ja — ohne Konto, und die Datei wird direkt nach der Umwandlung gelöscht.",
                ),
            ],
        },
    },
    ("jpg", "png"): {
        "en": {
            "title": "Convert JPG to PNG online — free",
            "meta": "Convert JPG to PNG online for free, no account. Lossless format for editing and transparency. Note: PNG files are larger. EU-hosted, files deleted right after.",
            "h1": "Convert JPG to PNG",
            "hero": "Convert a JPG into a lossless PNG for editing or transparency.",
            "when": "Convert JPG to PNG when you need a lossless copy for further editing, or a format that supports transparency. Useful before layering graphics, adding a transparent background in an editor, or when a tool requires PNG input.",
            "tech": "PNG is lossless, but converting from JPG cannot restore detail JPG already discarded — and the PNG will be noticeably larger (often several times) for photographic content. Pick PNG for graphics and editing; for sharing a photo, JPG or WebP stay smaller.",
            "faq": [
                (
                    "Will the image look better as PNG?",
                    "No — PNG can't recover detail JPG already lost. It just stores the current pixels losslessly, which is useful for editing, not for improving quality.",
                ),
                (
                    "Why is the PNG so much bigger?",
                    "PNG is lossless, so photographic content compresses far less than JPG's lossy compression. Expect a substantially larger file.",
                ),
                (
                    "Do I need an account?",
                    "No. JPG→PNG is free and account-free; the file is deleted right after conversion.",
                ),
            ],
        },
        "de": {
            "title": "JPG in PNG umwandeln — kostenlos",
            "meta": "JPG kostenlos online in PNG umwandeln, ohne Konto. Verlustfreies Format für Bearbeitung und Transparenz. Hinweis: PNG ist größer. EU-gehostet, sofort gelöscht.",
            "h1": "JPG in PNG umwandeln",
            "hero": "Ein JPG in ein verlustfreies PNG für Bearbeitung oder Transparenz umwandeln.",
            "when": "Wandle JPG in PNG um, wenn du eine verlustfreie Kopie zum Weiterbearbeiten oder ein Format mit Transparenz brauchst. Praktisch vor dem Überlagern von Grafiken, dem Freistellen im Editor oder wenn ein Tool PNG verlangt.",
            "tech": "PNG ist verlustfrei, aber die Umwandlung aus JPG kann bereits verworfenes Detail nicht zurückholen — und das PNG wird bei Fotos spürbar größer (oft mehrfach). Wähle PNG für Grafiken und Bearbeitung; zum Teilen eines Fotos bleiben JPG oder WebP kleiner.",
            "faq": [
                (
                    "Sieht das Bild als PNG besser aus?",
                    "Nein — PNG kann von JPG verworfenes Detail nicht zurückholen. Es speichert nur die aktuellen Pixel verlustfrei, was für die Bearbeitung nützlich ist, nicht für bessere Qualität.",
                ),
                (
                    "Warum ist das PNG so viel größer?",
                    "PNG ist verlustfrei, fotografische Inhalte komprimieren also weit weniger als mit JPGs verlustbehafteter Kompression. Erwarte eine deutlich größere Datei.",
                ),
                (
                    "Brauche ich ein Konto?",
                    "Nein. JPG→PNG ist kostenlos und ohne Konto; die Datei wird direkt nach der Umwandlung gelöscht.",
                ),
            ],
        },
    },
    ("webp", "jpg"): {
        "en": {
            "title": "Convert WebP to JPG online — free",
            "meta": "Convert WebP to JPG online for free, no account. A universally compatible JPG for apps that don't support WebP. Files deleted right after conversion.",
            "h1": "Convert WebP to JPG",
            "hero": "Convert a modern WebP image into a universally supported JPG.",
            "when": "Convert WebP to JPG when an app, editor or older program won't open WebP. Many downloads come as WebP today; JPG is the safe fallback that opens in virtually everything.",
            "tech": "Both are lossy; the JPG will usually be a bit larger than the WebP, which compresses more efficiently. Transparency, if present, is flattened onto white. Metadata is stripped and the file is processed server-side then deleted immediately.",
            "faq": [
                (
                    "Why won't my WebP open elsewhere?",
                    "Some older apps and software never added WebP support. JPG is the most universally compatible image format, so it opens nearly everywhere.",
                ),
                (
                    "Is quality lost?",
                    "There's one re-encode at high quality, so the difference is visually minimal for normal use.",
                ),
                (
                    "Is it free?",
                    "Yes — no account, and your file is deleted right after conversion.",
                ),
            ],
        },
        "de": {
            "title": "WebP in JPG umwandeln — kostenlos",
            "meta": "WebP kostenlos online in JPG umwandeln, ohne Konto. Universell kompatibel für Apps und Software ohne WebP-Unterstützung. Sofort gelöscht, EU-gehostet.",
            "h1": "WebP in JPG umwandeln",
            "hero": "Ein modernes WebP-Bild in ein universell unterstütztes JPG umwandeln.",
            "when": "Wandle WebP in JPG um, wenn eine App, ein Editor oder ein älteres Programm WebP nicht öffnet. Viele Downloads kommen heute als WebP; JPG ist der sichere Fallback, der praktisch überall funktioniert.",
            "tech": "Beide sind verlustbehaftet; das JPG wird meist etwas größer als das WebP, das effizienter komprimiert. Vorhandene Transparenz wird auf weiß gelegt. Metadaten werden entfernt, die Datei serverseitig verarbeitet und sofort gelöscht.",
            "faq": [
                (
                    "Warum öffnet mein WebP woanders nicht?",
                    "Manche ältere Apps und Programme haben WebP nie unterstützt. JPG ist das universellste Bildformat und öffnet sich nahezu überall.",
                ),
                (
                    "Geht Qualität verloren?",
                    "Es gibt eine Neukodierung in hoher Qualität, der Unterschied ist im normalen Gebrauch minimal.",
                ),
                (
                    "Ist es kostenlos?",
                    "Ja — ohne Konto, und deine Datei wird direkt nach der Umwandlung gelöscht.",
                ),
            ],
        },
    },
    ("jpg", "webp"): {
        "en": {
            "title": "Convert JPG to WebP online — free",
            "meta": "Convert JPG to WebP online for free, no account. Smaller files for faster websites at the same quality. Files deleted right after conversion, EU-hosted.",
            "h1": "Convert JPG to WebP",
            "hero": "Convert a JPG to WebP for smaller, faster-loading web images.",
            "when": "Convert JPG to WebP when you're optimising images for the web. WebP delivers the same visual quality at a noticeably smaller size, which speeds up page loads and saves bandwidth.",
            "tech": "WebP is typically 25–35% smaller than an equivalent-quality JPG. Both are lossy, so quality stays comparable. Modern browsers all support WebP; for old software, keep a JPG fallback. Conversion is server-side with immediate deletion.",
            "faq": [
                (
                    "How much smaller is WebP?",
                    "Usually 25–35% smaller than a JPG of comparable quality — a meaningful saving across many images on a site.",
                ),
                (
                    "Do all browsers support WebP?",
                    "Yes, all current browsers do. Only very old software might not, in which case keep the JPG as a fallback.",
                ),
                (
                    "Is it free?",
                    "Yes — no account, and the file is deleted right after conversion.",
                ),
            ],
        },
        "de": {
            "title": "JPG in WebP umwandeln — kostenlos",
            "meta": "JPG kostenlos online in WebP umwandeln, ohne Konto. Kleinere Dateien für schnellere Websites bei gleicher Qualität. Dateien sofort gelöscht, EU-gehostet.",
            "h1": "JPG in WebP umwandeln",
            "hero": "Ein JPG in WebP für kleinere, schneller ladende Web-Bilder umwandeln.",
            "when": "Wandle JPG in WebP um, wenn du Bilder fürs Web optimierst. WebP liefert die gleiche sichtbare Qualität bei spürbar kleinerer Größe, was Ladezeiten verkürzt und Bandbreite spart.",
            "tech": "WebP ist typisch 25–35% kleiner als ein qualitativ gleichwertiges JPG. Beide sind verlustbehaftet, die Qualität bleibt also vergleichbar. Alle modernen Browser unterstützen WebP; für alte Software ein JPG als Fallback behalten. Die Umwandlung läuft serverseitig mit sofortiger Löschung.",
            "faq": [
                (
                    "Wie viel kleiner ist WebP?",
                    "Meist 25–35% kleiner als ein JPG vergleichbarer Qualität — über viele Bilder einer Website eine deutliche Ersparnis.",
                ),
                (
                    "Unterstützen alle Browser WebP?",
                    "Ja, alle aktuellen Browser. Nur sehr alte Software evtl. nicht — dann das JPG als Fallback behalten.",
                ),
                (
                    "Ist es kostenlos?",
                    "Ja — ohne Konto, und die Datei wird direkt nach der Umwandlung gelöscht.",
                ),
            ],
        },
    },
    ("png", "webp"): {
        "en": {
            "title": "Convert PNG to WebP online — free",
            "meta": "Convert PNG to WebP online for free, no account. Much smaller web images that keep transparency. Files deleted right after conversion, EU-hosted, open source.",
            "h1": "Convert PNG to WebP",
            "hero": "Convert a PNG to WebP for smaller web images that keep transparency.",
            "when": "Convert PNG to WebP when you want smaller web graphics without giving up transparency. WebP supports an alpha channel like PNG but compresses far better — ideal for logos, icons and UI assets on a website.",
            "tech": "WebP keeps PNG's transparency while often being several times smaller. It supports both lossless and lossy modes; for photographic PNGs the saving is largest. All modern browsers support WebP. Processing is server-side with immediate deletion.",
            "faq": [
                (
                    "Does WebP keep transparency?",
                    "Yes — unlike JPG, WebP has an alpha channel, so transparent PNGs stay transparent.",
                ),
                (
                    "How much smaller is it?",
                    "Often several times smaller than the PNG, especially for photographic or richly-coloured images.",
                ),
                (
                    "Is it free?",
                    "Yes — no account, and the file is deleted right after conversion.",
                ),
            ],
        },
        "de": {
            "title": "PNG in WebP umwandeln — kostenlos",
            "meta": "PNG kostenlos online in WebP umwandeln, ohne Konto. Viel kleinere Web-Bilder mit erhaltener Transparenz. Dateien sofort gelöscht, EU-gehostet, Open Source.",
            "h1": "PNG in WebP umwandeln",
            "hero": "Ein PNG in WebP für kleinere Web-Bilder mit erhaltener Transparenz umwandeln.",
            "when": "Wandle PNG in WebP um, wenn du kleinere Web-Grafiken willst, ohne auf Transparenz zu verzichten. WebP unterstützt wie PNG einen Alphakanal, komprimiert aber deutlich besser — ideal für Logos, Icons und UI-Elemente auf einer Website.",
            "tech": "WebP behält PNGs Transparenz und ist oft mehrfach kleiner. Es beherrscht verlustfreie und verlustbehaftete Modi; bei fotografischen PNGs ist die Ersparnis am größten. Alle modernen Browser unterstützen WebP. Die Verarbeitung läuft serverseitig mit sofortiger Löschung.",
            "faq": [
                (
                    "Behält WebP die Transparenz?",
                    "Ja — anders als JPG hat WebP einen Alphakanal, transparente PNGs bleiben also transparent.",
                ),
                (
                    "Wie viel kleiner ist es?",
                    "Oft mehrfach kleiner als das PNG, besonders bei fotografischen oder farbreichen Bildern.",
                ),
                (
                    "Ist es kostenlos?",
                    "Ja — ohne Konto, und die Datei wird direkt nach der Umwandlung gelöscht.",
                ),
            ],
        },
    },
    ("docx", "pdf"): {
        "en": {
            "title": "Convert DOCX to PDF online — free",
            "meta": "Convert Word DOCX to PDF online for free, no account. Lock the layout for sharing, printing and archiving. Files deleted right after conversion, EU-hosted.",
            "h1": "Convert DOCX to PDF",
            "hero": "Turn a Word document into a fixed-layout PDF for sharing.",
            "when": "Convert DOCX to PDF when you need to share or submit a Word document that looks identical on every device — CVs, contracts, reports and official forms. PDF prevents the layout from shifting between Word versions.",
            "tech": "Text, headings and tables are preserved. On a full deployment, complex documents (footnotes, headers/footers, multi-section layouts) route to a high-fidelity engine; the slim deployment uses a pure-Python fallback that simplifies those features — surfaced as a notice. Files are processed server-side and deleted immediately.",
            "faq": [
                (
                    "Will my formatting be preserved?",
                    "Standard text, headings and tables convert faithfully. Very complex Word features may be simplified on the slim deployment; the tool tells you when that happens.",
                ),
                (
                    "Is the PDF editable?",
                    "It's a normal PDF — viewable everywhere and printable. For text extraction back out, use a PDF→TXT conversion.",
                ),
                (
                    "Do I need an account?",
                    "No. DOCX→PDF is free and account-free; your document is deleted right after conversion.",
                ),
            ],
        },
        "de": {
            "title": "DOCX in PDF umwandeln — kostenlos",
            "meta": "Word-DOCX kostenlos online in PDF umwandeln, ohne Konto. Layout fixieren zum Teilen, Drucken und Archivieren. Dateien sofort gelöscht, EU-gehostet.",
            "h1": "DOCX in PDF umwandeln",
            "hero": "Ein Word-Dokument in ein layouttreues PDF zum Teilen umwandeln.",
            "when": "Wandle DOCX in PDF um, wenn du ein Word-Dokument teilen oder einreichen musst, das auf jedem Gerät identisch aussieht — Lebensläufe, Verträge, Berichte und offizielle Formulare. PDF verhindert, dass das Layout zwischen Word-Versionen verrutscht.",
            "tech": "Text, Überschriften und Tabellen bleiben erhalten. Bei vollem Deployment werden komplexe Dokumente (Fußnoten, Kopf-/Fußzeilen, mehrteilige Layouts) an eine High-Fidelity-Engine geleitet; das schlanke Deployment nutzt einen Python-Fallback, der diese Funktionen vereinfacht — mit Hinweis. Dateien werden serverseitig verarbeitet und sofort gelöscht.",
            "faq": [
                (
                    "Bleibt meine Formatierung erhalten?",
                    "Standardtext, Überschriften und Tabellen werden originalgetreu umgewandelt. Sehr komplexe Word-Funktionen können im schlanken Deployment vereinfacht werden; das Tool weist darauf hin.",
                ),
                (
                    "Ist das PDF bearbeitbar?",
                    "Es ist ein normales PDF — überall anzeigbar und druckbar. Um Text wieder herauszuholen, nutze eine PDF→TXT-Umwandlung.",
                ),
                (
                    "Brauche ich ein Konto?",
                    "Nein. DOCX→PDF ist kostenlos und ohne Konto; dein Dokument wird direkt nach der Umwandlung gelöscht.",
                ),
            ],
        },
    },
    ("html", "pdf"): {
        "en": {
            "title": "Convert HTML to PDF online — free",
            "meta": "Convert HTML to PDF online for free, no account. Archive a web page or report as a fixed-layout PDF. No external resources fetched. Files deleted right after.",
            "h1": "Convert HTML to PDF",
            "hero": "Render an HTML file into a fixed-layout PDF document.",
            "when": "Convert HTML to PDF when you want to archive a web page, invoice or report as a stable, shareable document. Useful for records, offline reading and attaching rendered output to emails.",
            "tech": "The HTML is rendered to PDF preserving inline styling and layout. For privacy and security, external resources (remote stylesheets, images, fonts and any file:// references) are never fetched — only the uploaded file's own content is used. Processing is server-side with immediate deletion.",
            "faq": [
                (
                    "Are remote images and styles included?",
                    "No. For security (SSRF protection) the renderer never fetches external URLs — embed/inline what you need before converting.",
                ),
                (
                    "Will it look exactly like my browser?",
                    "Inline styles and layout render closely; pages that depend on remote CSS or JavaScript will differ, since neither is fetched or executed.",
                ),
                (
                    "Is it free?",
                    "Yes — no account, and your file is deleted right after conversion.",
                ),
            ],
        },
        "de": {
            "title": "HTML in PDF umwandeln — kostenlos",
            "meta": "HTML kostenlos online in PDF umwandeln, ohne Konto. Eine Webseite oder einen Bericht als layouttreues PDF archivieren. Keine externen Ressourcen. EU-gehostet.",
            "h1": "HTML in PDF umwandeln",
            "hero": "Eine HTML-Datei in ein layouttreues PDF-Dokument rendern.",
            "when": "Wandle HTML in PDF um, wenn du eine Webseite, Rechnung oder einen Bericht als stabiles, teilbares Dokument archivieren willst. Praktisch für Belege, Offline-Lesen und das Anhängen gerenderter Ausgaben an E-Mails.",
            "tech": "Das HTML wird unter Erhalt von Inline-Styling und Layout zu PDF gerendert. Aus Datenschutz- und Sicherheitsgründen werden externe Ressourcen (entfernte Stylesheets, Bilder, Schriften und jegliche file://-Referenzen) nie abgerufen — nur der Inhalt der hochgeladenen Datei wird genutzt. Die Verarbeitung läuft serverseitig mit sofortiger Löschung.",
            "faq": [
                (
                    "Werden entfernte Bilder und Styles eingebunden?",
                    "Nein. Aus Sicherheitsgründen (SSRF-Schutz) ruft der Renderer nie externe URLs ab — binde Benötigtes vor der Umwandlung inline ein.",
                ),
                (
                    "Sieht es genau wie im Browser aus?",
                    "Inline-Styles und Layout werden originalgetreu gerendert; Seiten, die auf entferntem CSS oder JavaScript beruhen, weichen ab, da beides nicht abgerufen oder ausgeführt wird.",
                ),
                (
                    "Ist es kostenlos?",
                    "Ja — ohne Konto, und deine Datei wird direkt nach der Umwandlung gelöscht.",
                ),
            ],
        },
    },
    ("eml", "pdf"): {
        "en": {
            "title": "Convert EML email to PDF — free",
            "meta": "Convert .eml email to PDF online for free, no account. Archive emails as PDF with headers and body for records. No tracking pixels fetched. EU-hosted.",
            "h1": "Convert EML (email) to PDF",
            "hero": "Save an .eml email as a PDF with its headers and body.",
            "when": "Convert EML to PDF when you need to archive or submit an email as a document — for records, expense claims, legal evidence or compliance. PDF is the stable format reviewers and archives expect.",
            "tech": "The PDF shows the key headers (From, To, Cc, Date, Subject) followed by the message body — the HTML part is rendered when present, otherwise the plain text. Remote tracking pixels and images are never fetched (SSRF protection / no read receipts). Processing is server-side with immediate deletion.",
            "faq": [
                (
                    "Which email files are supported?",
                    "Standard .eml files (RFC 822/MIME), which most mail clients can export. Outlook .msg is not yet supported — export to .eml first.",
                ),
                (
                    "Are tracking pixels loaded?",
                    "No. Remote images, including tracking pixels, are never fetched — so converting can't trigger a read receipt.",
                ),
                (
                    "Does it include attachments?",
                    "The page renders the email's headers and body. Attachments aren't embedded into the PDF in this version.",
                ),
            ],
        },
        "de": {
            "title": "EML-E-Mail in PDF umwandeln — gratis",
            "meta": ".eml-E-Mails kostenlos online in PDF umwandeln, ohne Konto. E-Mails mit Kopfzeilen und Text als PDF archivieren. Keine Tracking-Pixel. EU-gehostet.",
            "h1": "EML (E-Mail) in PDF umwandeln",
            "hero": "Eine .eml-E-Mail mit Kopfzeilen und Text als PDF speichern.",
            "when": "Wandle EML in PDF um, wenn du eine E-Mail als Dokument archivieren oder einreichen musst — für Akten, Spesenabrechnungen, Beweismittel oder Compliance. PDF ist das stabile Format, das Prüfstellen und Archive erwarten.",
            "tech": "Das PDF zeigt die wichtigsten Kopfzeilen (Von, An, Cc, Datum, Betreff) und darunter den Nachrichtentext — der HTML-Teil wird gerendert, falls vorhanden, sonst der Klartext. Entfernte Tracking-Pixel und Bilder werden nie abgerufen (SSRF-Schutz / keine Lesebestätigung). Die Verarbeitung läuft serverseitig mit sofortiger Löschung.",
            "faq": [
                (
                    "Welche E-Mail-Dateien werden unterstützt?",
                    "Standard-.eml-Dateien (RFC 822/MIME), die die meisten Mail-Programme exportieren können. Outlook-.msg wird noch nicht unterstützt — vorher nach .eml exportieren.",
                ),
                (
                    "Werden Tracking-Pixel geladen?",
                    "Nein. Entfernte Bilder, auch Tracking-Pixel, werden nie abgerufen — die Umwandlung kann also keine Lesebestätigung auslösen.",
                ),
                (
                    "Sind Anhänge enthalten?",
                    "Die Seite rendert Kopfzeilen und Text der E-Mail. Anhänge werden in dieser Version nicht ins PDF eingebettet.",
                ),
            ],
        },
    },
}


def get_pair_content(src: str, tgt: str, locale: str) -> dict | None:
    """Return the localized content dict for a pair, or None if not curated."""
    entry = PAIR_CONTENT.get((src.lower(), tgt.lower()))
    if entry is None:
        return None
    return entry[normalize_locale(locale)]


def related_pairs(src: str, tgt: str, limit: int = 5) -> list[tuple[str, str]]:
    """Curated pairs related to (src, tgt) for the internal link graph: pairs
    sharing the same target first (the "X → PDF" family), then the same source,
    then the rest — all drawn only from PAIR_CONTENT, self excluded."""
    src, tgt = src.lower(), tgt.lower()
    keys = [k for k in PAIR_CONTENT if k != (src, tgt)]
    same_tgt = [k for k in keys if k[1] == tgt]
    same_src = [k for k in keys if k[0] == src and k not in same_tgt]
    rest = [k for k in keys if k not in same_tgt and k not in same_src]
    return (same_tgt + same_src + rest)[:limit]


# The /convert/<slug> route splits the slug on the first "-to-". Guard the
# assumption (executably) that no format token itself contains "-to-", which
# would otherwise mis-parse the slug. None of the curated pairs do today.
assert not any("-to-" in s or "-to-" in t for s, t in PAIR_CONTENT), (
    "a PAIR_CONTENT format token contains '-to-' — this breaks /convert/<slug> parsing"
)


# Links surfaced in the global footer (every page) — spreads internal link
# equity to the pair pages and aids discovery. Language-neutral arrow labels
# (e.g. "JPG → PDF") so they need no translation; the path is localized
# per-request via localized_url in the template. Order follows PAIR_CONTENT.
FOOTER_LINKS: list[dict[str, str]] = [
    {"label": f"{format_label(s)} → {format_label(t)}", "path": f"/convert/{s}-to-{t}"}
    for (s, t) in PAIR_CONTENT
]
