### Changed — the upload is deleted as soon as the result exists

Single-file conversions and compressions, page extraction and PDF compression
now delete the uploaded file — the copy in the request's temporary folder and
the web framework's own — as soon as the result is written, instead of
together with the result when the response ends. Inserting pages already
deleted its own copies early; it, splitting and redaction now release the
framework's copy early too, and a PDF → PDF conversion writes its result over
the upload. Batch requests release the framework's copy of each file as soon
as it is copied.
