### Fixed — a multi-page TIFF keeps every page

Compressing a multi-page TIFF (a scanned letter, a fax) handed back only its
first page — the others were gone without a word — and TIFF → PDF, TIFF →
TIF and inserting it into a PDF made one page of it. Now compressing and
TIFF → TIF keep every page, each packed losslessly and stripped of its
metadata like a single picture, and TIFF → PDF and "Insert pages" make a
page of each; a black-and-white page stays black and white (CCITT Group 4)
instead of turning into a colour JPEG ten times its size. A page that can't
be read gets a `400` saying so — not a server error, and not fewer pages
without a word.

- Converted to a picture format (PNG, JPG, …) a multi-page TIFF still gives
  its first page, and now says so: "Only the first page of this TIFF was
  converted. Convert it to PDF to keep every page." — for several files at
  once too (API: `X-FileMorph-Warnings: pages=first`, per file in
  `X-FileMorph-Batch-Notes`).
- The pages together may take as much memory as one colour image at the
  size limit (`FILEMORPH_IMAGE_MAX_MEGAPIXELS`, 89 by default) — about forty
  black-and-white A4 pages at 300 dpi — up to 1 000 pages, read within 15
  seconds: they are decoded at once. A larger TIFF gets a `400`
  (`tiff_too_large`) whose message, in the page's language, says to split
  it.
