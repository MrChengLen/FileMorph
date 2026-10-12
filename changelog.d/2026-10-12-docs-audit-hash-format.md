### Changed — compliance docs describe the audit hash format

The TOM annex, the DPA template, the security questionnaire, the security
overview and the /enterprise page say what an audit entry's hash covers in
the current format: the event type, the UTC timestamp, the payload and the
previous entry's hash. Each entry records its format (`hash_version`), and
`app/core/audit.py` specifies each one. The texts state that the account ID
stays outside the hash so that account deletion can clear it, and point
auditors to `VERIFY_CHAIN_SQL` in `app/core/audit.py`: the full-chain check
in plain Postgres SQL that runs on a database dump. The questionnaire adds
that keeping the newest entry's `id` and `record_hash` outside the database
also shows changes the chain cannot show on its own, such as entries removed
from its end.

- **Guard.** `tests/test_audit_log.py` fails if one of these docs stops
  naming `VERIFY_CHAIN_SQL`.
