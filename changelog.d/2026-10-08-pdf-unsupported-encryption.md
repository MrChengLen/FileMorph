### Fixed — a certificate-encrypted PDF gets a 400 that says so, not a 500

A PDF encrypted with something other than a password — a certificate
(`/Adobe.PubSec`) or a DRM plug-in's own security handler — failed on every
PDF path. pypdf raises `NotImplementedError` while it opens such a file, or
one with an unsupported `/V`, `/SubFilter` or crypt-filter method, and
nothing caught it: `/pdf/extract`, `/pdf/split` and `/convert` (PDF → TXT,
PDF → PDF) answered a generic 500 and logged a traceback, and
`/convert/batch` reported "Conversion failed. Verify the file is valid."
pikepdf raises a plain
`PdfError` instead, so `/pdf/compress` told the user to verify the file and
logged a traceback, and PDF → PDF/A answered a 500; where Ghostscript is
installed (the Docker image ships it), the file reached Ghostscript, which
can't decrypt it either.

All these paths now answer `400` with a new code,
`X-FileMorph-Error-Code: pdf_encryption_unsupported`, and "This PDF is
protected with a certificate or an unsupported encryption. Remove the
protection (e.g. ask the sender for an unprotected copy) and try again."
PDF → PDF/A refuses the file before Ghostscript runs. The PDF tool pages and
the converter show the text in German or English; `/convert/batch` reports it
for the file. The two PDF libraries don't always agree on what is
unsupported: `/pdf/compress` and PDF → PDF/A (pikepdf) answer `pdf_encrypted`
for a `/SubFilter` or an unknown crypt-filter method under the standard
handler, which qpdf takes for a password problem.

`pdf_encrypted` keeps its meaning, "the PDF needs a password", because no
password opens a certificate-encrypted file; hence the separate code. Only
the opening step is guarded: there pypdf raises `NotImplementedError` only
while it reads the encryption dictionary (checked in pypdf 6.19); later the
same error means an unsupported stream filter, which has nothing to do with
encryption.
