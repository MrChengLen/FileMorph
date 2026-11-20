### Security — a `*` or `null` among the CORS origins no longer turns credentials on; tests that could not fail now can

`CORS_ORIGINS` turns credentials off whenever the list contains `*`, alone or
next to other origins, or `null` (the origin of every sandboxed iframe and
`data:`/`file:` page). Until now only the exact value `*` did: with
`CORS_ORIGINS=*,https://example.com` every site was answered with its own
origin and credentials. The default (`http://localhost:8000`) and explicit
origin lists behave as before.

The test suite was reviewed test by test. Tests that stayed green whatever the
code did were rewritten or removed, and checks that were missing were added:

- The CORS rule, the decompression-bomb warning, the e-mail token types, the
  "no exception text to the client" rule, the database-error log redaction and
  the rate-limit tests now fail when their protection is removed. Each was
  checked by breaking the code on purpose.
- New: the admin cockpit refuses anonymous and regular users on every one of
  its API routes; the monthly API-call limit (429) and the capacity limit
  (503) are enforced on all eight file routes; every extracted message is in
  both translation catalogues; the scope guard's local hooks and its workflow
  block the same paths; `/pdf/insert` names an unsupported PDF encryption and
  the field it came in.
- Removed: tests that passed for any outcome or repeated a stronger test.
