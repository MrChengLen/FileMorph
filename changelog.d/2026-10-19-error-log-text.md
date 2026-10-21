### Fixed — logged errors keep their type and location, not their text

A logged exception now records the exception types and the traceback —
where it failed — but no longer the exceptions' texts. Those texts can quote
the uploaded file (document text, media metadata, addresses in a document's
markup), and the privacy notice says no file content is logged. This applies
to every logged exception, so database, payment and mail errors show their
type too; an `OSError` keeps its errno name (for example `[ENOSPC]`).

- ffmpeg, Ghostscript and LibreOffice errors carry the exit status; the
  tool's stderr goes into the error only with `APP_DEBUG=true`.
- The loggers of WeasyPrint, fontTools and pypdf, and library warnings
  (routed to the `py.warnings` logger), are silent: they quote refused URLs,
  font names, raw bytes of a malformed PDF object or sheet titles. A real
  failure still reaches the converter as an exception.
- uvicorn's own line for an exception that escapes past the 500 handler
  keeps its format and loses the text; uvicorn's other lines and the access
  log are unchanged.
- The PDF compressor's "skipping undecodable image" line names the error
  type only.
- With `APP_DEBUG=true` the log keeps the full texts and the library output —
  for local debugging only; `.env.example` and `docs/self-hosting.md` say so.

`tests/test_log_privacy.py` pins it: a logged failure keeps both types,
Python's chain separators and the frames but no text unless APP_DEBUG is on;
`from None` drops the context; the four loggers are silenced; uvicorn's
exception line drops the text; a malformed PDF quotes nothing into the log;
the three tools quote their stderr only with APP_DEBUG; and the refused image
URL of an HTML upload reaches no log line. `docs/vendor-security-questionnaire.md`
and `docs/dpa-tom-annex.md` name the new guard.
