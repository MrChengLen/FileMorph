### Security — pypdf 6.21.2 and opentelemetry-api 1.45.1

pypdf moves from 6.19.0 to 6.21.2. That fixes the eight advisories published on
2026-10-21/22: infinite loops and unbounded memory use on crafted PDFs (seven,
moderate) and unvalidated JPEG image data (one, low). Uploads to the PDF tools
could reach them. opentelemetry-api, which FastAPI pulls in, moves from 1.45.0
to 1.45.1, which bounds the parsing of the W3C `tracestate` header
(GHSA-xcq7-p3pf-p88h, moderate). Both are floors in `requirements.txt`, so a
later re-lock cannot fall back below them; nothing else in the lockfile moved.
