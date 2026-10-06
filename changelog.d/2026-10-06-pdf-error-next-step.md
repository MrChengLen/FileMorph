### Fixed — a password-protected PDF says so, and two PDF errors stop blaming a page selection

A PDF that needs a password to open got the answer for a broken file on every
PDF path: "Could not read the PDF. Verify the file is valid." on
`/pdf/extract`, `/pdf/split` and `/convert` (PDF → TXT, PDF → PDF), "PDF
compression failed. Verify your file is a valid PDF." on `/pdf/compress`, and
a 500 on PDF → PDF/A; the last two also logged a traceback. Checking the file
can't help; the password is in the way. pypdf raises `FileNotDecryptedError`
on such a file and pikepdf `PasswordError`; all these paths now answer `400`
with `X-FileMorph-Error-Code: pdf_encrypted` and "This PDF is
password-protected. Remove the password (e.g. open the file and print it to a
new PDF) and try again." The PDF tool pages and the converter show that text
in German or English; `/convert/batch` reports it for the file. A PDF that
opens without a password is processed as before.

`/pdf/extract` answered a PDF without pages with `invalid_page_selection`, so
its web page asked the user to fix a page selection that was fine. It now
sends `invalid_pdf`, as `/pdf/split` already did. And `/convert` from PDF to
PDF without a page selection, which keeps every page, said "Too many pages
selected." for a document over 10 000 pages although nothing was selected;
the message now names the document's size and points to
`/api/v1/pdf/extract` for processing it in parts.

Tests build small PDFs in-process: locked with RC4-128, AES-128 and AES-256,
encrypted without an open password, without pages, and longer than a lowered
page cap. `scripts/make_testdata_pdf_error_messages.py` writes
byte-stable fixtures for checking this by hand to a gitignored local folder;
only the script ships.
