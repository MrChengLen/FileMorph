### Changed — the audit log no longer records IP addresses

Audit events written while handling a request used to carry the caller's IP
address in `audit_events.actor_ip` — anonymous conversions included — and the
append-only log keeps its rows. Now nothing on the audit path receives the
client address: `record_event()` has no parameter for one, no route passes it,
and the ORM no longer maps the column. (The online-cancellation events never
recorded one.)

- **Upgrade note (deployments with a database).** Rows written before this
  change keep their stored address for now. The nullable `actor_ip` column
  stays in the table, unmapped, and new rows leave it empty. A follow-up
  migration will drop the column together with the addresses in it. If you
  must keep them (a legal hold, say), export them before that release:
  `COPY (SELECT id, occurred_at, actor_ip FROM audit_events WHERE actor_ip IS NOT NULL) TO STDOUT WITH CSV HEADER`.
- **Texts.** The privacy policy gains §2h on the audit log: what an entry
  records, that it keeps no IP address, how long entries are kept (no time
  limit yet; automatic deletion is planned) and what account deletion changes.
  PII redaction moves to §2i. The DPA template, records of processing,
  self-hosting guide and `.env.example` no longer list an audit-log IP
  address; the security questionnaire and security overview now state that
  none is recorded. The DPA template, records of processing and security
  questionnaire add that a built-in retention job is planned. The security
  overview also stops calling upload metadata unpersisted: the audit log keeps
  the format, byte counts, tier and data-classification label.
- **Guard.** `tests/test_audit_no_ip.py` sends requests from an RFC 5737
  address through the real routes and fails if that address — or a shortened
  or hashed form of it — lands in any audit column, or if a new row fills the
  legacy column. It also scans `app/` for any audit call that could pass a
  client address, and for `actor_ip` anywhere in application code. The docs
  are checked the same way, and the privacy page in both languages.
