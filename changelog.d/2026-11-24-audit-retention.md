### Changed — audit entries are kept for three years; the old IP addresses are deleted

The audit log kept its entries without a time limit, and the entries written
before it stopped recording IP addresses (2026-10-10) still held the caller's
address.

- **Three years.** At every start and then once a day, the app deletes audit
  entries older than three years (`delete_expired_events` in
  `app/core/audit.py`). It keeps the newest expired entry as the start of the
  chain until a younger one expires, and appends an entry recording how many
  it deleted. `verify_chain` and `VERIFY_CHAIN_SQL` accept the oldest entry's
  link to a deleted one only when such a record names it and was written
  about three years after that entry. The period is fixed.
- **Database guard.** Migration 015 widens the append-only trigger by exactly
  that deletion; every other deletion is still refused, also to the app's
  own database login. A new statement trigger refuses `TRUNCATE`, which the
  row triggers never saw. The trigger function now runs with a fixed
  `search_path`. The table's owner can still switch the triggers off.
- **IP addresses.** Migration 014 drops `audit_events.actor_ip` and rewrites
  the table (`VACUUM FULL`), so the addresses also leave the table's files.
- **Upgrade note (deployments with a database): this release deletes data.**
  The first start runs both migrations: the stored IP addresses go at once,
  entries older than three years in the first daily run (the audit log
  exists since May 2026, so no installation has such entries before May
  2029). To keep the addresses (a legal hold, say), export them before you
  update:
  `COPY (SELECT id, occurred_at, actor_ip FROM audit_events WHERE actor_ip IS NOT NULL) TO STDOUT WITH CSV HEADER`.
  The rewrite locks `audit_events` while it runs and needs free disk space
  for one copy of the table; on a small table it takes seconds, and the app
  starts once it is done. It runs as the table's owner, which the app's
  database login is (also after "Without the database superuser" in
  `docs/self-hosting.md`). Database dumps made before the update still
  contain the addresses.
- **Texts.** The privacy policy (§ 2h, German and English, dated 2026-11-25)
  now says that the stored addresses are deleted and how long entries are
  kept. The DPA template drops its retention placeholder; it, the TOM annex,
  the records of processing, the security questionnaire (including the
  advice to keep `occurred_at` with an external anchor), the security
  overview and the self-hosting guide state the period.
- **Tests.** On Postgres: both migrations up and down (014 rewrites the
  table), the trigger on both sides of the three-year boundary, `TRUNCATE`
  refused, a deletion run with both chain checks passing afterwards, and a
  deletion without its record, a forged record and a malformed record failing
  both. On SQLite: what a run deletes and keeps, runs years apart, a forged
  or future-dated record, nothing deleted when the record fails, and the
  start-up and daily runs. The guard against IP addresses in the audit log
  stays.
