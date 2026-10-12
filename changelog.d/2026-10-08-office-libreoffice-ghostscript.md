### Security — office image: the LibreOffice subprocess runs without Ghostscript

On the `filemorph:office` image, DOCX→PDF conversion can delegate to a
LibreOffice (`soffice`) subprocess that parses the uploaded document. As
defense-in-depth, that subprocess now runs with a reduced environment: the
application's secrets (signing key, database URL, Stripe and SMTP credentials)
are dropped from it, and a Ghostscript stub is placed ahead of any real `gs`
on its `PATH`, so the subprocess cannot start Ghostscript.

FileMorph's own PDF/A re-render resolves Ghostscript in the app process and is
unaffected, as is the pure-Python (mammoth) conversion path. Routing tests
pin the subprocess environment (`tests/test_office_gs_isolation.py`), and the
pull-request Docker build exercises a DOCX→PDF conversion on the office image.
`docs/security-overview.md` notes it.
