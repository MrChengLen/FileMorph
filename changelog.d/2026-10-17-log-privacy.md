### Fixed — server logs leave out email addresses, IP addresses and link tokens, as the privacy notice says

The privacy notice says the logs record the URL path, an email domain
instead of the address, and no IP address from the limiters. Four places
logged more:

- **Links in account emails** — email confirmation and password reset —
  carry their token after `#` (`/verify-email#token=…`,
  `/reset-password#token=…`). Browsers never send that part to the server,
  so neither the token nor the address a confirmation token was issued for
  reaches an access log. Links sent before this change (`?token=…`) still
  work; the page moves the token behind `#`.
- **The application server's access log** (uvicorn) drops the query string
  and keeps the path.
- **Mail delivery** logs the recipient's domain only. It no longer logs the
  subject, which carries the sender's own text for contact-form messages. A
  failed send records the error type, the SMTP reply code (for a refused
  recipient: the codes) and, for a connection problem, aiosmtplib's own text
  naming the SMTP host and port — no longer the server's reply, which can
  quote the recipient address. That error is no longer chained onto the one
  the routes log.
- **The concurrency cap** logs whether the caller was an account or an IP
  address, not the account id or the address itself. **The contact form's
  spam trap** no longer logs the IP address.

A database error's text no longer carries the statement's values either: a
failed insert used to print the address and the password hash into the error
that gets logged.

`docs/vendor-security-questionnaire.md`,
`docs/records-of-processing-template.md` and `docs/email-setup.md` describe
the logs this way. `tests/test_log_privacy.py` pins it: both link builders
put the token after `#` and both landing pages read it from there; a real
uvicorn server logs a request's path without its query; a refused
recipient's address and a message subject appear in no log line; neither
limiter log line nor the spam-trap line holds an IP address or an account
id; and the database engine hides statement values.
