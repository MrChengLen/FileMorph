### Fixed — a request's temporary files go however it ends, and the sweep runs every 10 minutes

A request's temporary folder (the upload and the result) is now removed as its
response ends, whether the download completed, was cut off or was stopped. Until
now it was removed by a task that runs only after a complete send.

A refused request now removes the folder before it writes its audit record. A
failing audit write (with `AUDIT_FAIL_CLOSED`) therefore no longer leaves the
folder behind.

LibreOffice and Ghostscript now keep their own temporary files in that folder,
or in an `fm_` folder of their own, instead of the system temp folder. The PDF/A
conversion writes its intermediate file next to the result. So nothing stays
behind in the system temp folder when a conversion stops halfway.

The background sweep removes folders that a crashed worker left behind. It now
runs every 10 minutes instead of every hour (`TEMP_SWEEP_INTERVAL_MINUTES`,
default `10`), so such a folder is gone within about 20 minutes, as the
homepage promises ("within minutes"). If you set the variable yourself, your
value still applies. That includes an `.env` copied from an older
`.env.example`, which sets it to `60`: change it to `10` or delete the line.
If you raise `MEDIA_SUBPROCESS_TIMEOUT_SECONDS` past ten minutes, raise
`TEMP_SWEEP_MAX_AGE_MINUTES` above it too.
