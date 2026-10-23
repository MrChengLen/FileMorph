### Security — pypdf 6.21.2 and opentelemetry-api 1.45.1

pypdf moves from 6.19.0 to 6.21.2. That fixes the eight advisories published on
2026-10-21/22: infinite loops and unbounded memory use on crafted PDFs (seven,
moderate) and unvalidated JPEG image data (one, low). Four of the seven, an
endless loop and three memory blow-ups in reading a PDF, could be reached
through uploads to the PDF tools and PDF → TXT; the other three and the JPEG
one sit in pypdf features FileMorph does not call.
opentelemetry-api, which FastAPI pulls in, moves from 1.45.0 to 1.45.1, which
bounds the parsing of the W3C `tracestate` header (GHSA-xcq7-p3pf-p88h,
moderate). Both are floors in `requirements.txt`, so a later re-lock cannot fall
back below them; nothing else in the lockfile moved.

The new pypdf also turns away a few rare PDFs that 6.19 read. PDF → TXT now
fails on a text run with an odd number of bytes in a font with two-byte
character codes (such as Identity-H, common for embedded fonts), and on more
than two million tokens in one page's content; PDF → TXT and the PDF tools
both fail on more than 100,000 entries in one array or dictionary. Such files
now get the "could not read" message.
