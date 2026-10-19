### Security — PDF/A conversion runs Ghostscript only on a file that starts as a PDF

A PDF/A conversion now runs its Ghostscript re-render stage only when the
upload's first non-blank bytes are the `%PDF-` header. An upload that carries
the header further in, or not at all, is refused with the existing caller-safe
`400` (`invalid_input`) before that stage, so only files that present as PDFs
reach Ghostscript.
