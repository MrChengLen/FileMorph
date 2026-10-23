### Changed — Conversion child processes set their limits as hard limits

On Linux the child processes that run the table conversions (XLSX → CSV,
CSV → XLSX, CSV → JSON, JSON → CSV), PDF compression and PDF → TXT set their
limits on address space, CPU time, file size and core dumps as hard limits,
which the child cannot raise again without root privileges. A child that
reaches its CPU-time limit is stopped with `SIGKILL` (status `-9` in the
server log); the request gets the same `400` as for the other limits.
