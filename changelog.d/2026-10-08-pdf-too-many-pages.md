### Fixed — a PDF over the 10 000-page cap is no longer called unreadable

`/pdf/split` takes at most 10 000 pages, but it answered a longer PDF with
`invalid_pdf`, so the split page said "Could not read the PDF. Verify the file
is valid." about a file that was fine, and offered no way forward.
`/pdf/extract` answered a selection of more than 10 000 pages with
`invalid_page_selection`, so its page explained the page-number syntax instead
of the limit.

Both now answer `400` with the new `X-FileMorph-Error-Code:
pdf_too_many_pages` and a message that names the cap and the next step. The
split page says to extract up to 10 000 pages at a time and split each part,
and links to "Extract PDF pages"; the extract page says to select fewer pages
or to extract them in several parts. Both texts are in German and English. The
other codes stay as they were, and so does `/convert`: PDF → PDF over the cap
keeps `invalid_input`, whose message already names the cap.

Tests lower the cap to two pages and check the engine, both routes, a request
exactly at the cap, the localized texts and the page wiring.
