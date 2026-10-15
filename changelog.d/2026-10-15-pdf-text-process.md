### Changed — PDF → TXT extracts the text in its own process, with a time limit

PDF → TXT (`/convert`) now runs pypdf in a child Python process
(`app/converters/_pdf_text.py`). The process is stopped after 30 seconds; on
Linux it may use at most 1 GiB of memory. A PDF too large or complex for that
gets `400` (`invalid_input`) with "This PDF is too large or complex to
extract its text in one go. Extract fewer pages with /api/v1/pdf/extract and
convert them in parts." Like the other PDF tools, PDF → TXT reads at most
10 000 pages; a larger PDF gets `400` with a message naming the cap. The
child gets no application secrets, like the LibreOffice subprocess, and its
diagnostic output is discarded. Password-protected, certificate-encrypted
and unreadable PDFs keep their existing answers.

The Docker image check on pull requests now converts a PDF to text inside
the image, so the child process is tested where it runs in production.
