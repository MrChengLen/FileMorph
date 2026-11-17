### Changed — PDF tools run with time and memory limits

Extracting pages (`/api/v1/pdf/extract`), splitting a PDF (`/api/v1/pdf/split`)
and PDF → PDF (`/api/v1/convert`, also in batches) now run in their own process
with time, memory and file size limits, like compressing a PDF and inserting
pages already do. The limits leave room for PDFs as large as the largest
upload; each request — in a batch, each file — takes a fraction of a second
longer.

- A PDF too large or complex for these limits gets a `400` that names the next
  step: `pdf_too_complex` for extract (select fewer pages) and split (extract
  fewer pages first, then split them), `invalid_input` for PDF → PDF.
- All other answers stay the same, including `invalid_pdf`,
  `invalid_page_selection`, `pdf_too_many_pages`, `pdf_encrypted`,
  `pdf_encryption_unsupported` and the `413` at the output cap.
