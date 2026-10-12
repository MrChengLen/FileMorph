### Changed — the audit log keeps nothing derived from an email address

Audit entries no longer hold a hash of an email address or an email domain.
The payload sits in the hash chain and can never be erased, and anyone who
knows an address can hash it and find the matching entries.

- A wrong-password login, a registration with a taken address and a
  password-reset request name the account they concern by its ID
  (`actor_user_id`), which a hard delete clears. An address without an
  account leaves no trace, and the client sees the same answer as before.
  Online cancellations already named a matching account this way.
- Contact-form entries keep only the language derived from the browser. Account-deletion entries
  no longer carry the email domain; the structured log still does, as the
  privacy policy says.
- **Texts.** The privacy policy (§2g, §2h), the DPA template, the records of
  processing, the TOM annex, the security questionnaire, the API reference and
  the account-deletion design describe this. They also state that entries
  written before this change keep their email hashes and domains (on
  filemorph.io: up to and including 12 October 2026): those sit in the hash
  chain too.
- When the confirmation email after an account deletion fails, the log line
  names the domain only, not the full address.
- **Guard.** `tests/test_audit_no_email.py` scans every audit call in `app/`
  and drives every auth and contact route that takes an email address, then
  checks every column of every audit row those requests wrote. The online
  cancellation is checked by `tests/test_billing_cancellation.py`.
