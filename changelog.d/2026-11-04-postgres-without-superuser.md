### Security — the Cloud overlay can run the app without the database superuser

By default the Cloud overlay's app logs in to Postgres as the superuser that
the postgres image creates from `POSTGRES_USER`. A superuser can run programs
in the database container (`COPY … FROM PROGRAM`) and read its files, so
anyone who got hold of the app's database login could too.

- With `POSTGRES_APP_PASSWORD` set in `.env`, `docker-compose.cloud.yml`
  builds `DATABASE_URL` for the role `filemorph_app`, which owns FileMorph's
  tables but is no superuser; without it, for the superuser as before, so
  existing installations keep working without a change. One variable
  switches name and password together. `docs/self-hosting.md` ("Without the
  database superuser") creates the role, hands it the tables of a new or an
  existing database, switches the app to it and then takes the superuser's
  login over the network away. It also describes the way back.
- The overlay sets `POSTGRES_PASSWORD` to an empty value in the app
  container, which `docker-compose.yml`'s `env_file` used to pass in from
  `.env`. The app never read it. Once the app uses its own role, the
  superuser's password no longer reaches the app container at all.
- The overlay's `postgres` service runs with `no-new-privileges`, without
  capabilities except the four its entrypoint needs to hand the data
  directory to the postgres user (`CHOWN`, `DAC_OVERRIDE`, `SETGID`,
  `SETUID`), with at most 256 processes and without core dumps. The first
  `up` after the update recreates the database container: the database is
  gone for a few seconds.
- CI runs the migrations and the Postgres tests as a role without superuser
  rights, so a migration that needs one fails there instead of on an
  installation, and starts the overlay's database with its restrictions.
- Migration 004 no longer makes Python print a `SyntaxWarning` whenever the
  migrations run, and ruff now reports such escapes.
