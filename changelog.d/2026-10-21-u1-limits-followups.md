### Fixed — limit messages offer a free account only where accounts exist, and the batch-size error speaks German

The limit messages offered callers without an account a free one ("Register
free …"). A Community Edition instance has no database and so no accounts:
signing up answers 503, and the hint led nowhere. Where an instance has no
accounts, the messages now point every caller to self-hosting, as they already
did for account holders. This covers the file-size, output-cap, target-size and
batch-size messages of the API and the web interface's texts for them.

- The batch-size 400 of `/convert/batch` and `/compress/batch` carries
  `X-FileMorph-Error-Code: batch_too_large`. The web interface showed the
  server's English text there, on the German pages too; it now shows its own
  text in both languages, and the "Costs and limits" link where the pricing
  page is on, as for the other limit errors.
- `docs/api-usage-guide.md` and `docs/api-reference.md` describe both cases and
  list the new error code.
