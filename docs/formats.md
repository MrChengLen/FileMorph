# Supported Formats

A complete reference of all supported input and output formats, with notes on quality, limitations, and common use cases.

---

## Images

### Conversions

| From | To | Notes |
|------|-----|-------|
| **HEIC / HEIF** | JPG, PNG, WebP, BMP, TIFF, GIF | iPhone / Apple device photos. Requires `libheif` on Linux (included in Docker). |
| **JPG / JPEG** | PNG, WebP, BMP, TIFF, GIF, ICO | Most common image format. Lossy — converting to PNG does not restore lost detail. |
| **PNG** | JPG, WebP, BMP, TIFF, GIF, ICO | Lossless. Supports transparency (alpha channel). |
| **WebP** | JPG, PNG, BMP, TIFF, GIF | Modern web format, excellent quality/size ratio. |
| **BMP** | JPG, PNG, WebP, TIFF, GIF | Uncompressed, large files. Rarely needed today. |
| **TIFF / TIF** | JPG, PNG, WebP, BMP, GIF | Used in print and archiving. |
| **GIF** | JPG, PNG, WebP, BMP, TIFF | Animated GIFs: only the first frame is converted. |

> **Note**: Converting from HEIC to any format requires ffmpeg or libheif to be installed.
> On Windows, `pillow-heif` handles this automatically. On Linux, install `libheif-dev`.

### Compression

Re-encode an image at a lower quality to reduce file size without changing format.

| Format | Compression method | Notes |
|--------|--------------------|-------|
| JPG | Lossy (JPEG quality 1–100) | Most effective. Quality 75–85 is a good balance. |
| PNG | Lossless (zlib level 0–9) | PNG is always lossless — "quality" controls compression speed, not visual quality. Smaller effect on file size than JPEG. |
| WebP | Lossy (quality 1–100) | Excellent compression. Comparable to JPEG but 25–35% smaller. |
| TIFF | Format save (no quality param) | TIFF supports multiple compression algorithms; basic optimization applied. |

**Typical size reduction (JPG at different quality levels)**:

| Original | Quality 90 | Quality 80 | Quality 70 | Quality 60 |
|----------|-----------|-----------|-----------|-----------|
| 5 MB | ~4 MB | ~3 MB | ~2.2 MB | ~1.7 MB |

---

## Documents

### Conversions

| From | To | Notes |
|------|-----|-------|
| **DOCX** | PDF | Two-engine routing — see [Notes on DOCX → PDF](#notes-on-docx--pdf) below. Word-grade fidelity in the `filemorph:office` image; pure-Python fallback in the slim image. |
| **DOCX** | TXT | Extracts plain text from all paragraphs. Formatting (bold, tables) is lost. |
| **TXT** | PDF | Creates a clean PDF with Helvetica font, A4 page size. |
| **PDF** | TXT | Extracts text from each page using PyPDF. Complex layouts (columns, forms) may not extract cleanly. |
| **Markdown (.md)** | HTML | Converts Markdown to a complete HTML document. Supports tables and fenced code blocks. |
| **Markdown (.md)** | PDF | Renders Markdown via HTML to PDF using WeasyPrint. Styled with a clean sans-serif font. |

### Notes on DOCX → PDF

DOCX → PDF runs through a **complexity router** that picks one of two
engines per conversion. Routing is controlled by the
`FILEMORPH_OFFICE_ENGINE` environment variable; the default is `auto`.

#### Two engines

| Engine | Library | Image variant | Fidelity | Speed |
|---|---|---|---|---|
| **High-fidelity** | LibreOffice headless (`soffice --convert-to pdf`) | `filemorph:office` | Word-grade — preserves footnotes, headers / footers, multi-section layout, table-of-contents fields, multi-level numbered lists, OLE objects, equations | Slower (cold ~3–5 s, subsequent ~1–2 s) |
| **Pure-Python** | `mammoth` (DOCX → HTML) + `WeasyPrint` (HTML → PDF) | Either — runs everywhere | Best-effort — strips footnotes / headers / footers / OLE, multi-level numbering flattens to nested lists, multi-section layout collapses to the document defaults | Fast (~0.5–1 s) |

#### How routing works (`auto` mode)

1. The router opens the DOCX as an OPC ZIP and probes for the features
   `mammoth` would silently lose: `word/footnotes.xml`,
   `word/endnotes.xml`, any `word/header*.xml` / `word/footer*.xml`,
   anything under `word/embeddings/`, two-or-more `<w:sectPr>` in
   `word/document.xml`, `<m:oMath>` (equations), `<w:ilvl w:val="N">` for
   N≥1 (multi-level numbered lists).
2. If any complex feature is present **and** `soffice` (or `libreoffice`)
   is on PATH, the router invokes LibreOffice.
3. If complex features are present **but** `soffice` is missing (running
   the slim image), the router falls back to `mammoth + WeasyPrint` and
   surfaces an `X-FileMorph-Warnings` response header so the caller knows
   fidelity was reduced — e.g.
   `X-FileMorph-Warnings: engine=mammoth_fallback, reason=soffice_unavailable, simplified=footnotes, simplified=headers`.
4. Simple DOCX with no complex features always takes the fast pure-Python
   path, regardless of which image is running.

To force a specific engine, set `FILEMORPH_OFFICE_ENGINE=libreoffice`
(fails loud if `soffice` is missing — recommended in the office image
when you never want the fallback) or `FILEMORPH_OFFICE_ENGINE=mammoth`
(always pure-Python; useful for A/B comparing the two engines on the
office image, or for self-hosters who explicitly accept the fidelity
ceiling for predictability).

#### Which image to pull

- **`ghcr.io/mrchenglen/filemorph:latest`** (slim, ~150 MB) — for
  self-hosters who don't run DOCX conversions or accept the
  pure-Python fidelity ceiling.
- **`ghcr.io/mrchenglen/filemorph:office`** (~430 MB) — adds
  LibreOffice + OFL Calibri/Arial/Times-metric fonts on top of the
  slim image. Recommended for Compliance Edition deployments, and for
  any deployment where Behörden / Kanzlei / Klinik Word documents flow
  through.

Both images are
[cosign-signed](release-signing.md). See
[`docs/self-hosting.md`](self-hosting.md) for the compose recipes.

#### Security

The pure-Python pipeline runs `WeasyPrint` with `_deny_url_fetcher`,
blocking any external resource load that a malformed DOCX might attempt;
the regression guard is
`tests/test_convert_document.py::test_docx_to_pdf_ssrf_blocked`.

The LibreOffice path runs `soffice --headless` with `--nolockcheck`,
`--norestore`, a per-conversion `UserInstallation` profile (so two
parallel conversions can't clobber each other's lockfiles), and a
60-second hard timeout. It runs as the same non-root `appuser` as the
rest of the container; the subprocess inherits the container's
`no-new-privileges` and dropped capability set from
`docker-compose.yml`.

---

## Spreadsheets & Data

| From | To | Notes |
|------|-----|-------|
| **XLSX** | CSV | Exports the active (first) sheet. Only cell values, no formatting or formulas. |
| **CSV** | XLSX | All data imported into a single sheet. No type detection — all values are stored as text. |
| **CSV** | JSON | Headers become keys. Result is a JSON array of objects. |
| **JSON** | CSV | Input must be a JSON array of objects with consistent keys. Nested values are flattened as strings. |

**Common use cases**:
- Export Excel data for Python/pandas analysis (XLSX → CSV)
- Import data from APIs into spreadsheets (JSON → CSV → XLSX)
- Share structured data between systems (CSV ↔ JSON)

---

## Audio

All audio conversions use **pydub** with ffmpeg as the backend.

### Conversions

| Format | Description | Common use case |
|--------|-------------|-----------------|
| **MP3** | Lossy, universal | Most compatible. Share and stream. |
| **WAV** | Lossless, uncompressed | Studio quality, editing. Large files. |
| **FLAC** | Lossless, compressed | Archiving. Same quality as WAV, ~50% smaller. |
| **OGG** | Lossy, open standard | Streaming, games. |
| **M4A / AAC** | Lossy, Apple format | iPhone recordings, iTunes. |
| **WMA** | Lossy, Microsoft format | Old Windows Media files. |
| **Opus** | Lossy, modern | Best quality at low bitrates (voice, streaming). |

Any of the above can be converted to any other format.

**Common conversions**:
- M4A → MP3 (iPhone voice memos → universal)
- FLAC → MP3 (archive → streaming)
- WAV → MP3 (reduce file size after recording)

> **Requires**: ffmpeg installed on the system.

---

## Video

All video conversions use **ffmpeg-python** (libx264 + AAC codec).

### Conversions

| Format | Description |
|--------|-------------|
| **MP4** | Universal, best compatibility. Recommended target. |
| **MOV** | Apple QuickTime. iPhone and macOS default. |
| **AVI** | Older Microsoft format. Wide software support. |
| **MKV** | Matroska. Open, supports multiple audio/subtitle tracks. |
| **WebM** | Browser-native video (Chrome, Firefox). Good for web embedding. |
| **FLV** | Flash Video. Legacy format. |
| **WMV** | Windows Media Video. Legacy Microsoft format. |

Any of the above can be converted to any other format.

**Common conversions**:
- MOV → MP4 (iPhone video → universal)
- AVI / MKV → MP4 (compatibility for phones, tablets, TVs)
- MP4 → WebM (web embedding without Flash)

### Compression

Video compression uses the **CRF (Constant Rate Factor)** method with libx264:

| Quality setting | CRF equivalent | Visual result |
|-----------------|----------------|---------------|
| 100 | 18 | Near-lossless |
| 80 | 22 | High quality (default for YouTube) |
| 70 | 25 | Good quality, moderate size |
| 60 | 28 | Acceptable, noticeable on large screens |
| 40 | 33 | Low quality, small file (previews, thumbnails) |

Output is always MP4 (H.264 + AAC), which offers the widest compatibility.

> **Requires**: ffmpeg installed on the system.

---

## Format not listed?

If you need a format that FileMorph does not yet support, you can:
1. [Open an issue](https://github.com/MrChengLen/FileMorph/issues) on GitHub
2. Add the converter yourself — see [Development Guide](development.md)
