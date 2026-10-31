### Changed — the health check's curl runs non-dumpable

`docker-compose.yml`'s health check runs `curl` in the container every 10
seconds, and Docker starts it as it starts every `docker exec` command: with
the container's environment. Both images now install curl execute-only for
every user but root, as they do tini, so the health check runs non-dumpable
and no other process of the container's user can read its environment. This
holds as long as the check runs curl directly, as `docker-compose.yml` does
(`["CMD", "curl", …]`), and with the container's capabilities dropped
(`cap_drop: [ALL]`); with Docker's default capabilities, the health check
stays dumpable.
