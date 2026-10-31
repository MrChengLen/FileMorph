### Changed — the Docker image runs under an init

Both images now start `tini` as PID 1, the container's init, which starts
`entrypoint.sh` and with it uvicorn: tini passes the signals the container
gets on to uvicorn and reaps child processes that end after their parent.
`docker stop` shuts uvicorn down as before, and the container still ends with
exit code 0.

Like the app process, tini holds the container's environment, and like it,
tini is non-dumpable, so no other process of the container's user can read
that environment: its program is execute-only for that user, and the image
starts it through `env`, which holds none of the capabilities Docker grants
the container's first process. The image
brings its own init, so leave Docker's off (`docker run --init`, `init: true`
in Compose or in the daemon's `daemon.json`): it would run ahead of tini with
the same environment, readable for the container's user.
