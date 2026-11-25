### Fixed — a download keeps its file's name instead of "result"

A file whose name had a space, a "ß" or letters of another script
(`Mein Urlaub.jpg`, `Grüße an Oma.jpg`, `foto (1).jpg`, `Отчёт.jpg`)
downloaded as `result.png` from the converter, the compress page and the PDF
tools. The server sends such a name as `filename*=UTF-8''…`, and the pages
read only `filename="…"`. They now read both forms through one script
(`app/static/js/download-name.js`), and without a name in the response they
name the result after the picked file instead of `result`.

- Names keep their accents and punctuation: `Grüße an Oma.png`, no longer
  `Gruße an Oma.png`; `Müller.png`, no longer `Muller.png`; `foto (1).png`,
  no longer `foto 1.png`. Removed are only path separators and the characters
  Windows forbids in a file name (with lookalikes such as `／`), control,
  format and unassigned characters, and dots and spaces at either end. A
  quote reaches the server as `%22` from a browser's form upload and is
  dropped too (`Angebot "final".jpg` → `Angebot final.png`). API clients: a
  name can now hold `;`, `$`, `&` or `'` — quote it before passing it to a
  shell.
- A name made only of such characters (`???.jpg`) becomes `result.png`; it
  used to come out as `png`, without an extension.
- Splitting a PDF and the AI redaction no longer fail with a server error for
  a name with letters beyond Western European ones (`Отчёт.pdf`,
  `Łódź.pdf`).
- Every route writes the header through one helper
  (`app/core/utils.py::content_disposition`): a name in plain ASCII without
  `%` as `filename="…"`, any other in both forms of RFC 6266, with an ASCII
  stand-in in `filename` for clients that read only that one. Names are
  capped at 200 bytes (UTF-8) instead of 200 characters, so a long name in a
  non-Latin script fits every file system.
