# Email Setup (Cloud Edition)

FileMorph's Cloud-overlay features — user registration with email verification,
password reset, account-deletion confirmation, and (optionally) Stripe billing
receipts — depend on outbound SMTP. This guide walks through configuring it for
a self-hosted deployment.

The Community Edition (anonymous-tier conversion / compression with API keys)
needs none of this. If you don't run the user-account features, leave the
`SMTP_*` envs empty and skip this document.

---

## What needs SMTP

| Feature | Endpoint | What email carries |
|---|---|---|
| Email verification | `POST /api/v1/auth/register` and `POST /api/v1/auth/resend-verification` | One-time link binding the verify-token to the user's email-at-issuance. **7-day TTL.** |
| Password reset | `POST /api/v1/auth/forgot-password` | Single-use reset link. **30-minute TTL**, invalidated by the next password change (hash-version pin). |
| Account-deletion confirmation | `DELETE /api/v1/auth/account` | Post-commit notification with the user-facing support contact. |
| Dunning / payment-failed | Stripe `invoice.payment_failed` webhook | "Update your card" notice, sent once per dunning cycle while Stripe retries the charge. |
| Billing receipts | Stripe Customer Portal | Stripe sends these directly via the customer portal — FileMorph itself only sends the transactional mail above. |

**Locale.** All of the above are rendered in the recipient's `preferred_lang`
(`de` / `en`) — seeded at registration from the locale the user signed up in,
changeable from the dashboard, and `PUT /api/v1/auth/account/language`. When it
is unset (NULL) the operator default `LANG_DEFAULT` applies. The dunning mail
fires from a Stripe webhook with no HTTP request to derive a locale from, which
is exactly why the column exists.

If `SMTP_HOST` is empty, every feature above degrades gracefully:

- `/forgot-password` and `/resend-verification` return `503 Service Unavailable`
  with a reason string the UI surfaces.
- `/register` still creates the user — the verification email is fire-and-forget.
  The user can request a fresh link via `/resend-verification` once SMTP is wired.
- `/auth/account` deletes the user even if the confirmation email cannot be sent;
  the deletion itself is the legally-binding action.

---

## Required environment variables

All documented in `.env.example`. The minimum for working transactional mail:

```env
SMTP_HOST=smtp.example.com           # your provider's SMTP relay
SMTP_PORT=587                        # 587 = STARTTLS, 465 = implicit SSL
SMTP_USERNAME=no-reply@example.com   # the auth user (often = FROM address)
SMTP_PASSWORD=...                    # provider-issued app password / SMTP secret
SMTP_FROM_EMAIL=no-reply@example.com # user-visible FROM address
SMTP_FROM_NAME=YourBrand             # display name in the From: header
SMTP_REPLY_TO=hallo@example.com      # optional; where users hit "reply"

APP_BASE_URL=https://your-domain.example.com  # used to build link URLs
```

`SMTP_FROM_EMAIL` and `SMTP_FROM_NAME` are what the recipient sees. There are
no hard-coded `@`-domains anywhere in the user-visible copy — every link, From:
address, and Reply-To: is taken from these variables. **Self-hosters ship their
own support identity end-to-end.**

If `SMTP_FROM_EMAIL` is empty, the sender falls back to `SMTP_USERNAME`. Set
both explicitly in production so the From: address never silently changes
because someone rotated the SMTP login.

---

## Picking a port (TLS mode)

The TLS mode is chosen by port, no extra flag:

- `SMTP_PORT=465` — implicit SSL from the first byte (`SMTPS`). Used by some
  legacy providers; less common today.
- `SMTP_PORT=587` — plain connect, then `STARTTLS` upgrade. The modern default.
  RFC 8314 § 3.3 recommends 587 for new deployments.

Some cloud providers (notably Hetzner Cloud at the time of writing) block
outbound port 465 for new accounts as anti-abuse, while leaving 587 open. If
your provider does the same, use 587 — it's the path of least friction. Open
465 only if your SMTP provider requires it and your hosting provider allows
the egress.

---

## Provider walk-throughs

The application talks to any RFC-compliant SMTP relay. Three common paths:

### A — Transactional ESP (Mailgun, Postmark, Brevo, ZeptoMail, Resend, …)

Best for production: deliverability is the ESP's full-time job, and you get
DKIM/SPF/DMARC alignment plus a deliverability dashboard.

Typical setup (vendor-specific values shown as placeholders):

```env
SMTP_HOST=smtp.<provider>.com
SMTP_PORT=587
SMTP_USERNAME=<api-username-or-token-key>
SMTP_PASSWORD=<api-token>
SMTP_FROM_EMAIL=no-reply@your-domain.example.com
SMTP_FROM_NAME=YourBrand
SMTP_REPLY_TO=hallo@your-domain.example.com
```

Verify the sending domain (`your-domain.example.com`) in the provider's
console before going live — most ESPs reject `From:` addresses on
unverified domains, and some put unverified senders into a sandbox mode
that only delivers to pre-allowlisted recipients.

### B — Mailbox provider's SMTP (Zoho Mail, Fastmail, Gmail Workspace, Mailbox.org, …)

Workable for low volume. The `From:` must usually match the authenticated
mailbox or a pre-configured alias.

```env
SMTP_HOST=smtp.<provider>.com
SMTP_PORT=587
SMTP_USERNAME=no-reply@your-domain.example.com
SMTP_PASSWORD=<app-password>          # NOT the account login password
SMTP_FROM_EMAIL=no-reply@your-domain.example.com
SMTP_FROM_NAME=YourBrand
SMTP_REPLY_TO=hallo@your-domain.example.com
```

Mailbox providers typically require an **app-specific password** rather than
the account login — generate it in the provider's security settings. They
also enforce per-mailbox sending caps; a high-volume deployment will outrun
them.

### C — Self-hosted relay (Postfix, Exim) on the same host

Possible but rarely worth it: residential-grade IP reputation makes
deliverability fragile, and you're now operating the SMTP stack on top of
the application stack.

```env
SMTP_HOST=127.0.0.1
SMTP_PORT=25                          # internal-only; not exposed externally
SMTP_USERNAME=                        # often empty for localhost relay
SMTP_PASSWORD=                        # often empty for localhost relay
SMTP_FROM_EMAIL=no-reply@your-domain.example.com
SMTP_FROM_NAME=YourBrand
```

Configure the local relay to forward via a reputable relay-host (your
ISP's smarthost, or a transactional ESP) so messages don't leave from a
residential IP block. Tighten port 25 to localhost-only at the OS firewall.

---

## Verifying the configuration

After setting the envs and restarting the container:

```bash
# Trigger a real password-reset email to a test account.
curl -X POST https://your-domain.example.com/api/v1/auth/forgot-password \
  -H "Content-Type: application/json" \
  -d '{"email": "your-real-inbox@example.com"}'
# Expected: 200 OK
# Expected: an email arrives at the inbox within seconds.
```

If no mail arrives, check:

1. **Application log** — the sender logs `send_email ok` (success) or
   `send_email failed` (failure). The latter is logged at exception level
   with full SMTP error details visible only in the server log; the HTTP
   response stays generic so the SMTP details never leak to the client.
2. **DNS / SPF / DKIM / DMARC** — for ESPs and mailbox providers, the
   sending domain must have valid SPF and DKIM records pointing at the
   provider, plus a DMARC policy. Without alignment, Gmail and Outlook
   silently drop or junk-folder the messages.
3. **Provider sandbox mode** — most ESPs ship new accounts in a sandbox
   that only delivers to pre-allowlisted recipients until the domain is
   verified.
4. **Outbound port** — confirm your hosting provider is not blocking
   the chosen port. Use `nc -vz <smtp-host> <port>` from inside the
   container to verify reachability.

---

## Privacy / DSGVO considerations

Outbound SMTP introduces a **sub-processor**: the provider that relays the
mail can read the recipient address, the message body, and the IP of the
sending host. List the provider in your own
[`docs/sub-processors.md`](sub-processors.md)-equivalent disclosure and
update your privacy policy accordingly.

The application sends **only** transactional content (auth flows + Stripe
receipts). It does not collect a marketing-consent flag, does not run
newsletter campaigns, and exposes no operator-side mailing surface. If you
add either, that's a new processing purpose under Art. 6 GDPR and needs its
own legal basis and disclosure.

The token TTLs documented above (`30 min` for password reset, `7 d` for
email verification) are conservative; operators with stricter security
policies can lower them by editing
[`app/core/tokens.py`](https://github.com/MrChengLen/FileMorph/blob/main/app/core/tokens.py).

---

## See also

- [`docs/installation.md`](installation.md) — env-var overview during initial setup
- [`docs/self-hosting.md`](self-hosting.md) — production deployment & reverse-proxy
- [`docs/api-reference.md`](api-reference.md) — auth endpoint contract incl. token TTLs
- [`docs/sub-processors.md`](sub-processors.md) — what to disclose if you accept users
- [`.env.example`](https://github.com/MrChengLen/FileMorph/blob/main/.env.example) — every supported variable with a one-line description
