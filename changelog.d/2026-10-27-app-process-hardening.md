### Changed — The app process keeps its environment and memory to itself; Ghostscript runs without the app's secrets; the image's code is read-only

On Linux the app process marks itself non-dumpable as it loads: no other
process of its user, the conversion child processes included, can read its
environment or memory through `/proc` or attach to it, and it writes no core
dump. A debugger or profiler that attaches to the running app (gdb, py-spy)
now needs root; in a container, root with the `SYS_PTRACE` capability.

Ghostscript, which re-renders PDF/A output, now gets the app's environment
without its secrets, as the conversion child processes and LibreOffice
already did.

In the Docker image the app's code belongs to root and is read-only for
`appuser`, whom the container runs as. Only `/app/data`, where the first start
writes the API key file, stays writable for it. A custom Dockerfile that still
runs `chown -R appuser:appuser /app` can limit it to `/app/data`.
