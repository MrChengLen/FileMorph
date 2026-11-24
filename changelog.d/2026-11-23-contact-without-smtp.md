### Fixed — contact form without outgoing email: no false "sent"

On an instance without SMTP (`SMTP_HOST` empty, the default for a fresh
self-hosted install), the contact form answered "your message has been sent"
although the message went nowhere: the mail was skipped. `/api/v1/contact` now
answers `503` there, and the page says that sending is not set up on this
server. When an operator address is configured (`CONTACT_FORM_RECIPIENT_EMAIL`,
else `SMTP_REPLY_TO` / `SMTP_FROM_EMAIL`), it names that address and offers a
"Write an email instead" button that opens the visitor's own mail program
with their subject and message filled in — also after too many attempts or a
server error. The bot honeypot still answers `200`. `docs/self-hosting.md`
gains a "Set up outgoing email (once)" step, and `docs/email-setup.md`
describes the new behaviour.
