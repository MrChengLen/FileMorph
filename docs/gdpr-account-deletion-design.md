# GDPR Account-Deletion Design

**Status:** Slice c.1 (free path) shipped 2026-05-06; slice c.2
(paid path with HGB §257 / AO §147 tax retention) is the next
follow-up. The endpoint, the cascade, the last-admin guard, the
confirmation email, and the audit-chain integration described in
§§ 3–9 are live; the Stripe-touched-account branch in § 5.B
currently returns HTTP 409 directing the user to the operator
support contact while the deleted_at column + partial unique
index land.
**Audience:** Self-hosters, contributors, and the FileMorph cloud
operator picking up slice c.2.
**Last updated:** 2026-05-06 (status row above; body preserved as
the design trail).

---

## 1. Why this doc exists

FileMorph's privacy policy (`app/templates/privacy.html`, § 5)
documents one path for account deletion: emailing
`privacy@filemorph.io`. There is no self-service "Delete account"
button in the dashboard. This document is the design specification
for the self-service flow that closes that gap.

It is **not** an implementation. The work breaks down into:

1. A new `DELETE /api/v1/auth/account` endpoint.
2. A "Danger zone" section in the dashboard with a re-confirmation
   flow.
3. A confirmation email sent after a successful deletion.
4. A privacy-policy text update reflecting the new path.
5. A bifurcated execution path: free / never-paid accounts are hard-
   deleted; accounts that have made at least one payment retain
   tax-relevant fields under German HGB §257 + AO §147 (10-year
   obligation, Art. 17(3)(b) GDPR exception). See § 5.B.

The endpoint name `DELETE /api/v1/auth/account` is the one already
called out in `docs/gdpr-privacy-analysis.md` (line 121, the C-2
section) as the cascade target required by Art. 17 of the GDPR.
This document keeps that name to avoid internal inconsistency.

### Cross-references

- `docs/gdpr-privacy-analysis.md` — data-flow analysis, Art. 17
  cascade requirements, and the EDPB one-month timeline.
- `app/templates/privacy.html` — privacy text (§ 2b and § 5 will
  be updated when the feature ships; the new wording is specified
  in § 10 below).
- `docs/security-overview.md` — defensive-transparency overview
  (auth, validation, data privacy).

This document does **not** add a GDPR Art. 15 data-export
endpoint; that is a separate design and a separate sprint.

---

## 2. Why self-service deletion now

Article 17 of the GDPR ("right to erasure") obliges the controller
to erase personal data on request, "without undue delay." The
European Data Protection Board recommends completion within one
month (`docs/gdpr-privacy-analysis.md`, line 443).

Today, FileMorph honours this through email-based deletion: a user
emails `privacy@filemorph.io`, the operator deletes the row
manually, and replies. That works, but it has three weaknesses:

1. **It depends on operator availability.** A weekend or holiday
   pushes deletions toward — and possibly past — the EDPB's
   one-month target.
2. **It is not self-auditable for the user.** The user has to
   trust the email reply; they cannot check the result themselves.
3. **It scales poorly.** Every deletion is manual operator work.

A self-service flow makes erasure immediate, observable to the
user, and zero-touch for the operator. It also makes the privacy
policy describe a button that exists, not just an email address.

---

## 3. Endpoint design

| Field | Value |
|---|---|
| Path | `DELETE /api/v1/auth/account` |
| Auth | `Depends(get_current_user)` (JWT bearer only) |
| Rate limit | `1/minute` per IP, via `slowapi` |
| Body schema (Pydantic) | `password: str`, `confirm_email: EmailStr`, `confirm_word: Literal["DELETE"]` |
| Success response | `204 No Content` |

The endpoint accepts a JSON body with three fields. All three must
match before deletion proceeds:

- `password` — the user's current password. Verified with the
  same bcrypt path as `POST /auth/login`.
- `confirm_email` — must equal the JWT subject's stored email
  address.
- `confirm_word` — must equal the literal string `DELETE`.

Each field defends a different mistake mode. `password` defends
against a stolen JWT. `confirm_email` defends against the user
being signed into the wrong account. `confirm_word` defends
against an accidental form submission.

API-key authentication (`X-API-Key`) is **not** accepted on this
endpoint. The API key is one of the things being deleted, and
using the very key whose deletion is being requested has
chicken-and-egg semantics. The web UI flow uses the JWT it
already holds; CLI users who want to delete an account sign in to
the dashboard.

### Status codes

| Code | Trigger |
|---|---|
| `204 No Content` | Deletion succeeded; no body returned. The internal path is hard-delete (free) or tax-retained (paid) — see § 4 + § 5.B. |
| `400 Bad Request` | `password`, `confirm_email`, or `confirm_word` did not match. |
| `401 Unauthorized` | No valid `Authorization: Bearer …` header, or the JWT has expired. |
| `409 Conflict` | The caller is the last active admin in the system (see § 9). |
| `500 Internal Server Error` | Stripe API failed before the database delete; nothing was deleted. See § 5. |
| `503 Service Unavailable` | Database not configured (consistent with `_db_required` in `app/api/routes/auth.py`). |

The `400` cases all return the same generic error string
("Confirmation did not match.") — the endpoint does not say which
of the three fields was wrong. This avoids leaking whether the
password was correct on a session whose JWT may have been stolen.

### Code anchor (after implementation)

The endpoint will be added to `app/api/routes/auth.py`,
immediately after `reset_password`. It reuses the existing
dependency patterns: `Depends(get_current_user)`, `_db_required`,
`@limiter.limit(…)`.

---

## 4. Cascade rules

The endpoint executes one of two paths depending on whether the
caller has ever made a payment:

- **Free / never-paid path** — full hard-delete of the `users` row
  (this section).
- **Paid path** — `users` row retained in a *restricted* state
  with personal fields except those required for German tax
  bookkeeping erased; ApiKeys still hard-deleted, related
  analytics rows still anonymized. See § 5.B for the trigger,
  the retained-field list, the 10-year purge schedule, and the
  legal basis (HGB §257 + AO §147 + Art. 17(3)(b) GDPR).

The PostgreSQL schema is already wired for the analytics-side
cascades. The relevant `ON DELETE` clauses live in
`app/db/models.py`:

| Entity | Cascade rule | Effect on FREE-account delete | Effect on PAID-account delete (§ 5.B) | Reason |
|---|---|---|---|---|
| `User` | (target row) | Hard delete | **Retained**, fields nulled selectively | Subject of erasure (free) / tax-restricted (paid). |
| `ApiKey.user_id` | `ON DELETE CASCADE` (line 96) | Auto-deleted | Application-level hard delete (no tax relevance) | API keys are 1:1 with the user and not invoice-relevant. |
| `FileJob.user_id` | `ON DELETE SET NULL` (line 123) | Anonymized; row retained | Anonymized; row retained | Aggregate analytics value; without `user_id`, the row is not personal data. |
| `UsageRecord.user_id` | `ON DELETE SET NULL` (line 153) | Anonymized; row retained | Anonymized; row retained | Tier-metric continuity. Billing is flat-rate (`Pro €7/mo`, `Business €19/mo`) — usage rows do not feed invoice line items, so anonymization is permissible even on paid accounts. |
| `UsageRecord.api_key_id` | `ON DELETE SET NULL` (line 158) | Anonymized via the `api_keys` cascade | Anonymized via the application-level ApiKey delete | Same reasoning, applied transitively. |
| Stripe customer record | (external) | Subscription cancelled; customer record retained by Stripe | Subscription cancelled; customer record retained by Stripe | Stripe's tax-retention obligation; already disclosed in `privacy.html` § 3a. |

### Why anonymize and not delete `FileJob` / `UsageRecord`?

GDPR Art. 4(1) defines personal data as "any information relating
to an identified or identifiable natural person." A `UsageRecord`
row that holds only `endpoint`, `timestamp`, `file_size_bytes`,
and `duration_ms` — with `user_id` and `api_key_id` set to `NULL`
— does not relate to an identifiable person. It is anonymous
operational data and falls outside the GDPR's scope of "personal
data."

Retaining the anonymized rows preserves operational value
(format-pair popularity for product decisions; size distributions
for capacity planning) without ongoing privacy risk. The user
delete is still complete in the sense the GDPR requires.

### What the implementation has to do

Because `ON DELETE CASCADE` and `ON DELETE SET NULL` are already
configured at the database level, the endpoint only has to delete
the `users` row. PostgreSQL handles the rest. The application
code does not have to walk the related tables manually.

The ORM-level relationship `User.api_keys` carries
`cascade="all, delete-orphan"` (line 78), which means SQLAlchemy
also cleans up in-memory state correctly when the session is
flushed.

---

## 5. Stripe handling and German tax-retention obligation

Two concerns sit on the payments boundary: cancelling the active
Stripe subscription so it stops billing (§ 5.A), and retaining
the FileMorph-side records that German tax law obliges us to
keep for ten years (§ 5.B). They are independent: § 5.A also
runs for never-paid accounts that happen to have a stale
`stripe_customer_id` (e.g. abandoned checkout); § 5.B only
triggers when at least one payment has actually completed.

### 5.A Subscription cancellation (cancel-first pattern)

A user with an active paid subscription cannot be deleted in
isolation: doing so orphans the Stripe subscription, which then
continues to bill (Stripe does not know the customer is gone on
our side).

The endpoint handles this with a **cancel-first** pattern:

1. Read `user.stripe_customer_id`. If `NULL`, skip to step 4.
2. Look up the customer's subscriptions via the Stripe API.
3. For each active subscription, call
   `stripe.Subscription.cancel(...)`.
4. If steps 2-3 succeeded (or there were no subscriptions),
   proceed with the database delete (§ 4).

If any Stripe API call in steps 2-3 fails, the endpoint returns
`500 Internal Server Error` and the database delete is **not**
performed. The user remains in the same state as before the
request. Atomicity matters here: half-deleting an account
(Stripe still billing, database row removed) is worse than not
deleting at all.

### Stripe customer record retention

Stripe retains customer records under its own tax and accounting
obligations, which it documents in its data-processing agreement
and which we already disclose in `privacy.html` § 3a. We do not
attempt to delete the Stripe customer record. The confirmation
email (§ 8) tells the user this in plain language.

### Code anchor (after implementation)

The Stripe interaction will be added to the existing billing
helper module (`app/core/billing.py` or its successor, depending
on the state of the module at implementation time). The new
helper looks something like
`cancel_active_subscriptions_for(customer_id: str) -> None`, and
it raises on Stripe API errors so the endpoint can map those to
`500`.

### 5.B Tax-retention path for paid accounts (HGB §257, AO §147)

FileMorph operates from Hamburg, Germany. As a German entity it
has its own bookkeeping and tax-retention obligations that are
independent of Stripe's:

- **HGB §257 Abs. 1 Nr. 4 + Abs. 4** — invoice copies
  ("Buchungsbelege") and accounting records must be retained for
  10 years from the end of the calendar year of the last entry.
- **AO §147 Abs. 1 + Abs. 3** — same 10-year retention applies to
  tax-relevant records under the tax code.
- **GDPR Art. 17(3)(b)** — the right to erasure does not apply
  where processing is necessary "for compliance with a legal
  obligation which requires processing by Union or Member State
  law to which the controller is subject." The German retention
  laws above are exactly such a Member-State legal obligation.

This means a hard-delete of an account that has issued or
received invoices would put FileMorph in violation of German tax
law. Stripe holding its own copy of the invoice on Stripe's side
does **not** discharge FileMorph's controller-side duty: a
German tax audit (Betriebsprüfung) requires that FileMorph can
itself demonstrate, from its own records, which customer
corresponds to which payment.

#### Trigger condition

The paid path activates when **either** of these is true at the
moment of deletion:

1. `User.stripe_customer_id IS NOT NULL` **and** at least one
   `Subscription` for that customer has ever transitioned to
   `active` (queried via the Stripe API as part of the
   cancel-first pass in § 5.A).
2. The application has any local invoice/payment record for the
   user (relevant only after a future schema addition; at this
   design's date there is no such local table).

If neither is true (free user, abandoned-checkout user without
ever-active subscription, or any account that has never paid),
the original hard-delete path from § 4 runs unchanged.

#### Retained fields on the `users` row

| Field | State after restricted delete | Why |
|---|---|---|
| `id` (UUID) | retained | Foreign-key anchor for invoice/usage linkage during a tax audit. |
| `email` | retained | Original customer identifier on the invoice; tax audit reconciles invoice → natural person. |
| `stripe_customer_id` | retained | Bridge to Stripe's invoice/payment records during audit. |
| `tier` | retained | Last billed tier; identifies the product line on the invoice. |
| `role` | reset to `user` | No admin privilege on a deleted account. |
| `created_at` | retained | Account-lifetime evidence for VAT periods. |
| `is_active` | set to `false` | Account cannot log in or be authenticated. |
| `password_hash` | replaced with sentinel `"DELETED:" + uuid4()` | No login is possible; the value is not a valid bcrypt hash and rejects all comparisons. The column is `NOT NULL`, so we cannot blank it. |
| `deleted_at` (new column) | set to `NOW()` | Marks the start of the 10-year retention clock. |

`ApiKey` rows are still removed at the application level
(equivalent to the CASCADE the free path triggers — keys are not
invoice-relevant). `FileJob` and `UsageRecord` are still
anonymized via `SET NULL` on `user_id`.

#### Schema additions (implementation sprint)

The implementing sprint adds:

- `users.deleted_at TIMESTAMPTZ NULL` (Alembic migration).
- A partial unique index on `email`:
  `CREATE UNIQUE INDEX ix_users_email_active ON users(email) WHERE deleted_at IS NULL`,
  replacing the existing unconditional `UNIQUE` constraint. This
  lets a customer re-register with the same email after a
  tax-restricted delete (the old, restricted row is kept; the
  new active row is independent).
- Login, password-reset, and `get_current_user` reject any row
  with `deleted_at IS NOT NULL`. The existing `is_active=False`
  check covers this transitively, but a redundant explicit guard
  on `deleted_at IS NULL` in the auth queries is recommended for
  defence-in-depth.

#### 10-year purge job

A separate sprint adds a periodic task (e.g. daily Caddy / cron
job) that runs:

```sql
DELETE FROM users
 WHERE deleted_at IS NOT NULL
   AND deleted_at < NOW() - INTERVAL '10 years 6 months';
```

The 6-month buffer keeps the row past the end of the calendar
year of the 10-year deadline (HGB §257 Abs. 4 starts the clock
"with the end of the calendar year" of the last accounting
entry; the buffer absorbs the year-end alignment plus any
in-flight tax audit). The exact buffer is operator-tunable; the
implementing sprint picks a value and documents it in
`docs-internal/filemorph-io-runbook.md`.

The purge job is **out of scope** for this design (its own
sprint), but the schema and the `deleted_at` marker are added
here so the purge job has something to act on.

#### What is *not* retained on the paid path

- File content — already deleted under the existing retention
  policy (24h / 7d / 30d by tier) long before the account is
  deleted.
- `password_hash` — replaced with a sentinel as described.
- `api_keys` — fully removed.
- `FileJob.user_id` and `UsageRecord.user_id` — `SET NULL`. The
  rows survive as anonymous aggregate data; without `user_id`
  they no longer relate to an identifiable person under
  Art. 4(1) GDPR.

#### Legal basis recap (for auditor questions)

> *"Why is FileMorph keeping data after the user asked for
> deletion?"* — Art. 17(3)(b) GDPR exempts processing required
> by a legal obligation under Member State law. HGB §257 and
> AO §147 require FileMorph to retain invoice-linkable records
> for 10 years. Once that period ends, the row is hard-deleted
> by the purge job.

The retained fields are the **minimum** needed to satisfy the
tax-audit trail (data minimisation under Art. 5(1)(c) GDPR is
honoured even inside the retention exception).

---

## 6. UI flow (dashboard)

The deletion flow lives in the dashboard, not on a separate page.
It mirrors the existing API-key revoke pattern (`dashboard.js`
lines 55-59): a single `confirm()` dialog plus a follow-up form,
no custom modal library.

### Step-by-step

1. **Danger zone.** A new section at the bottom of the dashboard,
   visually separated from account settings, titled "Danger zone."
   It contains a single button: "Delete account."

2. **Button styling.** Red text and a red border, mirroring the
   existing revoke-API-key button (`dashboard.html` line 29:
   `border border-red-900 text-red-400`). No hover animation;
   this is a destructive action and should look like one.

3. **First-pass confirmation.** Clicking the button calls native
   `confirm("This will permanently delete your account, API keys,
   and cancel any active subscription. Conversion-job records are
   anonymized. Continue?")`. The same pattern as
   `dashboard.js:56`. If the user clicks "Cancel," nothing
   happens.

4. **Inline form.** If `confirm()` returns `true`, an inline form
   appears in the same section. Three fields:
   - "Type your email address to confirm:" (text input).
   - "Enter your password:" (password input).
   - "Type the word `DELETE` to confirm:" (text input).
   The "Delete account" button is replaced by a "Confirm
   deletion" submit button. A "Cancel" link removes the form
   and brings the original button back.

5. **Submission.** The form submits with
   `fetch("/api/v1/auth/account", { method: "DELETE", … })`
   carrying the JWT in the `Authorization` header and the three
   fields in the JSON body.

6. **Success path (204).** The handler runs `localStorage.clear()`
   to drop the JWT and any cached API-key value, then redirects
   to `/account-deleted`, a minimal landing page that says
   "Your account has been deleted. You'll receive a confirmation
   email shortly. You can re-register at any time." The page has
   a single link back to `/`.

7. **Failure paths.** A `400` shows "Confirmation did not match.
   Try again." in the form. A `409` shows the last-admin message
   from § 9 directly. A `500` shows "Something went wrong on our
   end. Your account is unchanged. Please try again or email
   privacy@filemorph.io." A `401` redirects to login.

8. **Confirmation email.** An email arrives at the user's
   registered address within roughly ten seconds (§ 8). It is
   informational; the deletion is already complete.

### Files the implementation will touch

- `app/templates/dashboard.html` — adds the "Danger zone"
  section.
- `app/static/js/dashboard.js` — adds the confirm-then-form
  handler.
- `app/templates/account_deleted.html` — new minimal landing
  page.
- `app/api/routes/pages.py` — route for `/account-deleted`.
- `app/api/routes/auth.py` — the new endpoint itself.

---

## 7. Audit log

Account-deletion events are logged to standard output via the
application's structured logger, **not** to a dedicated database
table. This matches the existing pattern in
`app/api/routes/auth.py:307` (password-reset email dispatch) and
keeps the design footprint small.

### Event format

```python
logger.info(
    "account_deletion",
    extra={
        "user_id": str(user.id),
        "tier": user.tier.value,
        "email_domain": email.split("@", 1)[1],
        "had_subscription": bool(user.stripe_customer_id),
    },
)
```

The log carries the `email_domain` rather than the full address.
That matches the promise in `privacy.html` § 2d: "structured JSON
without plaintext email addresses — only the email domain is
kept for debug purposes."

### Retention

Log retention follows the hosting infrastructure's defaults. On
production deployments behind Caddy, logs are typically retained
for around thirty days, which lines up with the EDPB's one-month
recommendation for handling erasure requests.

### Future work (out of scope here)

A dedicated `audit_log` table —
`(actor_id, action, target_id, timestamp, metadata_json)` —
would make admin-action review easier and survive log rotation.
That is a separate sprint and a separate design document; this
design intentionally does not introduce it.

---

## 8. Confirmation email

After a successful deletion, the endpoint sends one email to the
deleted user's registered address using the existing SMTP helper
(`app/core/email.py::send_email`).

### Subject

`Your FileMorph account has been deleted`

### Body (informational)

The body covers four things and **branches by path** (free vs.
paid, see § 4 + § 5.B):

1. **What happened, and when.** "Your FileMorph account
   (`<email>`) was deleted on `<ISO timestamp>`."
2. **What was deleted / anonymized in both paths.**
   - Login credentials (password) are erased.
   - All API keys are removed.
   - Any active paid subscription is cancelled.
   - The conversion-job history is anonymized (account ID
     stripped; records are retained as anonymous aggregate
     data under Art. 4(1) GDPR).
3. **What was retained — free path.** "Stripe transaction
   records, retained independently by Stripe under its
   tax-retention obligations, with a link to Stripe's privacy
   policy."
4. **What was retained — paid path (additional sentence).**
   "Because your account had at least one completed payment,
   German tax law (HGB §257 + AO §147) obliges us to retain a
   minimal invoice-link record — your email address, customer
   identifier, and last billing tier — for 10 years from the
   end of the calendar year of your last payment. After that
   period it is permanently deleted. This is permitted under
   Art. 17(3)(b) GDPR (legal obligation exception). No further
   processing of the retained data takes place; it is held
   solely for tax audit."

The email also notes that re-registration with the same address
is possible at any time (the partial unique index in § 5.B
allows this even after a paid-path delete) and creates a fresh
account with no link to the deleted one.

### Failure handling

If SMTP is down, the email send fails. The deletion is **not**
rolled back — the database row is already gone, and the user
explicitly asked for deletion. The failure is logged via
`logger.exception(...)`, the same pattern that
`forgot_password` uses (`auth.py:311`). If a user contacts
support to confirm a deletion they never received an email for,
the operator can confirm from the audit log (§ 7).

---

## 9. Edge cases

### Last active admin

A user with `role == admin` who is the only `is_active=True,
role=admin` row in the database cannot delete their own account.
The endpoint returns `409 Conflict` with the message:

> You are the only active admin. Promote another user to admin
> before deleting your account.

This applies both to self-hosters with a single admin account
(common) and to the cloud operator (where there is typically more
than one admin, but the guard still belongs in the endpoint).

### Active subscription

Handled in § 5. The subscription is cancelled before the database
delete; a Stripe error blocks the delete entirely.

### In-flight `FileJob` rows (`status=processing`)

A conversion in flight at the moment of deletion is not aborted.
Once the database commit lands, the job's `user_id` becomes
`NULL` through the `ON DELETE SET NULL` cascade. The worker
continues to run, but the output is discarded because there is
no longer a user context to return it to. This is acceptable:
the user explicitly asked for deletion, and the conversion was
already in flight; we do not promise mid-flight delivery to
deleted accounts.

### Pending password-reset token

A reset token issued before deletion becomes invalid the moment
the user row is gone. The token decoder in `reset_password`
(`auth.py:332`) looks the user up by ID and rejects the token if
`is_active` is false or the row is missing. The user gets the
generic 400 "Reset link is invalid or has expired."

### Concurrent deletion (double-click race)

Two near-simultaneous `DELETE /api/v1/auth/account` requests for
the same user: the first commits and removes the row; the second
runs `Depends(get_current_user)`, fails the user lookup, and
returns `401`. No double-delete, no orphaned rows.

### Re-registration with the same email

Allowed. The unique constraint on `users.email` is enforced only
across **existing** rows. Once the row is gone, the email is
free. A new registration creates a fresh account with a new UUID,
no link to the deleted account, no inherited subscription, no
inherited API keys. The privacy text (§ 10) makes this explicit.

### No-password accounts (legacy / SSO)

Out of scope. The Cloud Edition currently authenticates only
through email + password. If single sign-on is added later, the
deletion flow has to be revisited to accept proof-of-identity
through the SSO provider; that is a future design.

---

## 10. Privacy-policy text update

The deletion feature requires two paragraph rewrites in
`app/templates/privacy.html`. Both are fully specified here so
the implementing sprint can apply them verbatim.

### § 2b — User accounts (Cloud Edition)

Current text (line 24, last sentence):

> Account data is persisted in our PostgreSQL database for the
> lifetime of your account and erased on deletion request (Art.
> 17 GDPR).

Replacement:

> Account data is persisted in our PostgreSQL database for the
> lifetime of your account. You can delete your account at any
> time through the dashboard's "Delete account" flow, or by
> request to privacy@filemorph.io. On deletion we erase your
> password hash and API keys, and cancel any active paid
> subscription. Conversion-job records are anonymized — your
> account ID is removed — and the resulting anonymous rows are
> retained for aggregate service-quality analytics; under GDPR
> Art. 4(1), they no longer relate to you. Stripe transaction
> records are retained by Stripe under their own tax-retention
> obligations. **For accounts that have made at least one
> payment, German tax law (HGB §257, AO §147) obliges us to
> retain a minimal invoice-link record — your email address,
> Stripe customer identifier, and last billing tier — for 10
> years from the end of the calendar year of your last payment;
> all other personal data is erased on deletion. This retention
> is the legal-obligation exception under GDPR Art. 17(3)(b);
> the data is held solely for tax audit and is hard-deleted at
> the end of the retention period.** Erasure otherwise complies
> with GDPR Art. 17.

### § 5 — Your rights (GDPR), "Account deletion" paragraph

Current text (line 50):

> **Account deletion:** To delete your account (email address,
> password hash, API keys, Stripe linkage), contact
> privacy@filemorph.io. Stripe may retain records of past
> transactions independently of our deletion, to comply with its
> own legal and tax obligations.

Replacement:

> **Account deletion:** You can delete your account at any time
> from the dashboard ("Delete account" in the Danger zone). The
> flow asks you to re-enter your email, password, and the word
> `DELETE` before deletion proceeds. Deletion permanently erases
> your password hash and API keys; cancels any active paid
> subscription; and anonymizes your conversion-job history
> (your account ID is stripped, the records are retained for
> analytics). Stripe retains transaction records independently
> to comply with its own tax-retention obligations. **If your
> account has made at least one payment, we additionally retain
> a minimal invoice-link record — email, Stripe customer ID,
> and last billing tier — for 10 years (HGB §257, AO §147,
> permitted under GDPR Art. 17(3)(b)); after that period the
> record is permanently deleted. Free accounts that never
> issued a payment are erased in full.** If you prefer, you
> can also request deletion by emailing privacy@filemorph.io.
> To exercise other rights (access, rectification, restriction),
> contact the same address.

### "Last updated" date stamp

The implementing sprint sets the date on line 9 to the deploy
date. This document does not pre-set a date.

---

## 11. Test plan

The implementing sprint adds `tests/test_account_deletion.py`
covering the following twelve cases. They are written here in
acceptance-test form so the implementation can adopt them
directly.

1. **Happy path — free account.** `DELETE /api/v1/auth/account`
   with the right password, the right `confirm_email`,
   `confirm_word="DELETE"`, and a valid bearer JWT returns `204`.
   The user has no `stripe_customer_id` and has never paid.
   After the response, the `users` row is gone, all `api_keys`
   rows for that user are gone, every related `file_jobs` row
   has `user_id=NULL`, and every related `usage` row has
   `user_id=NULL`.

2. **Wrong password** → `400`.

3. **Wrong `confirm_email`** → `400`.

4. **Wrong `confirm_word`** → `400`.

5. **Missing `Authorization` header** → `401`.

6. **Last admin.** A test fixture with a single admin user calls
   the endpoint → `409`. Promoting a second user to admin first
   lets the original admin succeed.

7. **Active Stripe subscription.** The user has
   `stripe_customer_id` set; the test mocks Stripe to report one
   active subscription. `stripe.Subscription.cancel` is called
   once, **before** the database delete. The order is asserted
   explicitly.

8. **Stripe API error.** Stripe is mocked to raise; the endpoint
   returns `500`, and the `users` row is still present.

9. **Confirmation email.** SMTP is mocked. After a successful
   deletion, `send_email` is called once with a subject
   containing "deleted" and a body containing the deletion
   timestamp.

10. **Login after deletion.** Posting the deleted user's
    credentials to `POST /auth/login` returns
    `401 "Invalid email or password."`.

11. **Forgot-password after deletion.** Posting the deleted
    user's email to `POST /auth/forgot-password` returns
    enumeration-safe `200` with the same body any other email
    would receive. No email is sent.

12. **Audit log shape.** During the happy path, the test asserts
    that one log record was emitted with the message
    `account_deletion`, `user_id=<uuid string>`, and
    `email_domain` set to the email domain only. **No**
    plaintext email is in the log record. The log also carries
    `deletion_mode` set to `"free"` or `"tax_retained"` so
    operators can slice deletion volume per path in dashboards.

13. **Paid path — tax-retained delete.** A user with
    `stripe_customer_id` set and at least one previously
    `active` Stripe subscription (mocked) calls the endpoint and
    receives `204`. After the response: the `users` row is
    **still present**; `email`, `stripe_customer_id`, and `tier`
    are unchanged; `is_active` is `false`; `password_hash`
    starts with the sentinel prefix `"DELETED:"`; `deleted_at`
    is set to a timestamp within the last few seconds; all
    `api_keys` rows for that user are gone; related `file_jobs`
    and `usage` rows have `user_id=NULL`.

14. **Login blocked after paid-path delete.** Posting the
    deleted-but-retained user's credentials to `POST /auth/login`
    returns `401 "Invalid email or password."` even with the
    correct old password (the sentinel hash rejects all
    bcrypt comparisons). Posting any password equally returns
    `401`.

15. **Re-registration of a paid-path-deleted email.** After the
    paid-path delete in test 13, `POST /auth/register` with the
    same email succeeds (the partial unique index allows it),
    creating a fresh row with a new UUID, new `stripe_customer_id
    = NULL`, and `tier = "free"`. The old retained row remains
    untouched.

16. **Sentinel password hash is rejected by bcrypt.** A unit test
    confirms that `verify_password(any_string, "DELETED:" + uuid)`
    returns `False` and does not raise. (Defence-in-depth — the
    `is_active=False` and `deleted_at IS NOT NULL` guards
    already block login one layer up.)

These tests run under the same fixtures as the rest of the auth
test suite — the in-memory SQLite engine from
`tests/conftest.py` and the `disable_rate_limiting` session
fixture. Tests 13 + 15 require Alembic to have applied the
`deleted_at` column and the partial unique index; tests skip
under SQLite if the partial index is not supported there
(SQLite supports partial indexes since 3.8.0; should be fine on
the in-memory engine).

---

## 12. Out of scope

This document is deliberately narrow. The following are **not**
covered, and the implementing sprint does not need to address
them:

- **GDPR Art. 15 data export.** The right of access is a
  separate feature with its own design document.
- **Retention-policy redesign for `FileJob` / `UsageRecord`.**
  The existing `ON DELETE SET NULL` is the policy this design
  relies on. Any future change there is a separate decision.
- **Soft delete with restore window.** The user explicitly asked
  for deletion; immediate hard delete (free path) or immediate
  restriction (paid path) is what Art. 17 expects. No restore
  is offered, and the paid-path restricted state is *not* a soft
  delete — the account cannot log in, and the retained fields
  are held only for the legal-obligation exception under
  Art. 17(3)(b).
- **10-year purge cron job.** The job that hard-deletes paid-
  path rows after the retention period (`DELETE FROM users
  WHERE deleted_at < NOW() - INTERVAL '10 years 6 months'`) is
  its own sprint. This design only adds the `deleted_at` marker
  the purge job will key on.
- **Local invoice/payment table.** This design relies on Stripe
  as the source of truth for invoice content; FileMorph's own
  retention is the minimal user→customer link. A future
  ledger-style local invoice table is a separate decision.
- **CLI subcommand** (e.g. `filemorph delete-account` over an
  API key). Web UI only. The API key being deleted cannot
  authenticate its own deletion.
- **`audit_log` database table.** Logged via stdout for now;
  the dedicated table is its own sprint.
- **Admin bulk-delete.** The admin cockpit keeps its existing
  per-user "Deactivate" flow. Bulk deletion is a different UX
  problem.
- **Stripe refund policy.** Subscription cancellation goes
  through Stripe's defaults (proration as configured on the
  product). Custom refund logic is not part of this design.
- **Multi-step email confirmation** with a click-through link.
  Re-confirmation happens in the UI **before** the request is
  sent. The email is sent **after** deletion, as confirmation,
  not as a confirmation step.
