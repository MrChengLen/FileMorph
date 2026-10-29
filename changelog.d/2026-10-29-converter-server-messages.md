### Fixed — the converter and the PDF tools show the server's common error messages in German

On German pages, these errors are now worded in German, by their error code:

- a conversion or compression that failed;
- an image too large to open safely (the PDF tools already did this);
- a file that starts like a program or script, with what to do next;
- an upload over the server's size limit, with that limit — for a batch,
  counting all its files together;
- a server too busy to take the request.

On English pages, the messages for a blocked file and an oversized upload
now name the next step too. Messages about a problem specific to one format
(for example a PDF that can't be read) and the reasons listed per file in a
batch are still in English.
