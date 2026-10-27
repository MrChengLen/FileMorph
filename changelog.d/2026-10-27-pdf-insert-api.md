### Added — insert pages into a PDF (API)

`POST /api/v1/pdf/insert` puts a whole second file into a PDF: another PDF, a
Word document (`.docx`, converted with LibreOffice) or an image, which becomes
one page in the size of the page next to it, turned to the image's
orientation. The pages go at the start, after a given page (`after_page`,
counted from the first page of the file, not by printed page numbers) or at
the end. The PDF keeps its bookmarks, which still lead to the right pages, its
links, form fields and document info; its page labels survive when the pages
are appended. A successful answer carries `X-FileMorph-Inserted-Pages` and
`X-FileMorph-Page-Count`; an error about one of the inputs names the form
field in `X-FileMorph-Error-Field`. A server without LibreOffice answers a
Word file with `word_not_converted` and the advice to insert it as a PDF. Both
files together may have at most 10 000 pages, and the request counts as one
call.
