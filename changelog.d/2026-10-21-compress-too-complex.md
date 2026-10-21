### Added — The PDF compress page names the next step for a PDF too large or complex to compress

When `/api/v1/pdf/compress` stops a PDF at its memory and time limits, it
answers `400` with a code of its own, `pdf_too_complex`, so a client can tell
this case from other input problems. The compress page (`/pdf/compress`) shows
the message in the visitor's language with a link to “Extract PDF pages”:
extract fewer pages at a time, then compress each part. A range of pages
needs far fewer steps than splitting the PDF into single pages and
compressing each one.
