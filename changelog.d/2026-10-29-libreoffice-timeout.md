### Fixed — a LibreOffice time limit stops all of LibreOffice

When a DOCX → PDF conversion through LibreOffice (office image) — including a
Word file inserted into a PDF — reaches `OFFICE_SUBPROCESS_TIMEOUT_SECONDS`,
the converter now stops LibreOffice's worker process (`soffice.bin`) together
with the `soffice` launcher, so the conversion ends completely at the limit.
For this, `soffice` runs in a process group of its own.
