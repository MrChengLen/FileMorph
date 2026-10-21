### Changed — Conversion child processes also limit the size of each file they write

On Linux the child processes that run the table conversions (XLSX → CSV,
CSV → XLSX, CSV → JSON, JSON → CSV), PDF compression and PDF → TXT now also
limit the size of each file they write (table conversions 2 GiB, PDF
compression and PDF → TXT 1 GiB), next to their memory and CPU-time limits. A
write past the limit ends the child, and the request gets the same `400`
whose message names the next step as for a file over the memory or time
limit.
