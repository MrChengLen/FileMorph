### Security — PDF → PDF/A only processes PDFs, and runs Ghostscript with -dSAFER

PDF → PDF/A now confirms an upload is a PDF before its Ghostscript re-render
stage. It reads the file's `%PDF-` header — the one the spec defines, found
within the first 1024 bytes, so a damaged-but-repairable PDF still qualifies
and keeps its Ghostscript repair pass. A file without the header skips
Ghostscript and gets `400` with `X-FileMorph-Error-Code: invalid_input` and
"This file is not a PDF. Convert it to PDF first, then upload the PDF to create
a PDF/A.", where a file that was not a PDF used to reach the re-render stage and,
failing that, the markup pass for a generic 500. The re-render also passes
`-dSAFER` to Ghostscript explicitly (its default since gs 9.50) so the sandbox
holds regardless of the installed version's default.

Ghostscript is faked in the tests, so they hold with or without it installed: a
non-PDF never reaches the re-render call, a damaged PDF that carries the header
still does, the route answers 400 rather than 500, and `-dSAFER` is in the
command.
