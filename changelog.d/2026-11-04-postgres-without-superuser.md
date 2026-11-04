### Security — the Cloud overlay can run the app without the database superuser

By default the Cloud overlay's app logs in to Postgres as the superuser that
the postgres image creates from `POSTGRES_USER`. A superuser can run programs
in the database container (`COPY … FROM PROGRAM`) and read its files, so
anyone who got hold of the app's database login could too.

- `docker-compose.cloud.yml` builds `DATABASE_URL` from `POSTGRES_APP_USER`
  and `POSTGRES_APP_PASSWORD` when they are set in `.env`, and from the
  superuser login as before when they are not: existing installations keep
  working without a change. `docs/self-hosting.md` ("Without the database
  superuser") creates a role that owns FileMorph's tables but is no
  superuser, hands it the tables of a new or an existing database, and
  switches the app to it.
- The app container no longer receives the superuser's password:
  `docker-compose.yml` passes every line of `.env` in through `env_file`, and
  the overlay now sets `POSTGRES_PASSWORD` to an empty value there. The app
  never read it.
- The overlay's `postgres` service runs with `no-new-privileges`, without
  capabilities except the four its entrypoint needs to hand the data
  directory to the postgres user (`CHOWN`, `DAC_OVERRIDE`, `SETGID`,
  `SETUID`), with at most 256 processes and without core dumps. The first
  `up` after the update recreates the database container: the database is
  gone for a few seconds.
- CI runs the migrations and the Postgres tests as a role without superuser
  rights, so a migration that needs one fails there instead of on an
  installation.
- Migration 004 no longer makes Python print a `SyntaxWarning` whenever the
  migrations run.
