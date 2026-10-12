### Changed — audit log: record hash format 2

New audit entries carry `hash_version = 2`: `record_hash` is the SHA-256 of
`v2`, the previous hash, the event type, the UTC timestamp and the canonical
payload, one per line. `app/core/audit.py` specifies it, together with
`VERIFY_CHAIN_SQL`, the same full-chain check in plain Postgres SQL for an
auditor working from a database dump. The actor column stays outside the
hash, so account deletion (Art. 17 GDPR) can clear it without breaking the
chain. Entries written earlier keep format 1 and verify as before;
`verify_chain` checks each entry with the format it names.

- **Upgrade note (deployments with a database).** Migration
  `013_audit_hash_version` adds the column with a constraint that allows
  formats 1 and 2. On Postgres it changes only the catalogue: no row is
  rewritten, and the append-only trigger does not fire. Its downgrade refuses
  once format-2 entries exist, because the older code cannot verify them.
- `occurred_at` is now stamped by the application, because the hash needs it
  before the row is written.
- `verify_chain(start_id=…)` checks a slice of the chain again: the slice's
  first row may chain from a row before it. It used to be reported as broken.
- **Guards.** `tests/test_audit_log.py` fails when a new `audit_events` column
  is neither hashed nor explicitly left out. `tests/test_audit_postgres.py`
  migrates entries from before 013 on real Postgres and checks that they still
  verify, that `VERIFY_CHAIN_SQL` agrees with `verify_chain`, and that account
  deletion still clears the actor on them. `tests/test_alembic_heads.py` fails
  when two migrations share a parent or a revision id is longer than the
  32 characters Alembic's version table holds.
