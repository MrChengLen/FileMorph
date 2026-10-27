### Changed — Conversion child processes isolate themselves further; the container caps processes and threads

On Linux the child processes that run the table conversions (XLSX → CSV,
CSV → XLSX, CSV → JSON, JSON → CSV), PDF compression and PDF → TXT now gain no
privileges through setuid programs, end when the app process that started them
ends, and start no processes or threads of their own unless the app runs as
root. Where the `jbig2dec` program isn't installed, as in the image, PDF → TXT
answers a PDF whose streams hold JBIG2 data (which pypdf decodes only with
that program) with the usual `400` for an unreadable PDF instead of a `500`.

`docker-compose.yml` caps the container at 4096 processes and threads and
turns off core dumps. The systemd unit in `docs/self-hosting.md` gets the same
two lines (`TasksMax=`, `LimitCORE=0`) plus `NoNewPrivileges=yes`,
`PrivateTmp=yes` and `ProtectSystem=strict`; a unit copied from the guide
earlier can take them over. On a host with many cores, raise the process cap
together with `MAX_GLOBAL_CONCURRENCY`.
