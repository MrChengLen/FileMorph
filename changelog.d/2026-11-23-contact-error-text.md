### Fixed — contact form and account deletion: error messages show their text

Two error paths showed no explanation at all:

- the contact form, when a message could not be sent (a missing e-mail
  address or a message under 20 characters, too many attempts, a server
  error);
- "Delete account" in the dashboard, when the deletion did not go through
  (the confirmation did not match, the last active admin, a server error).

The texts sit in `data-err-NNN` attributes, and a dash before a digit stays in
the browser's dataset key (`data-err-400` is `dataset['err-400']`), so the
scripts' `dataset.err400` found nothing. Both scripts now read the texts with
`getAttribute('data-err-' + code)`, as the cancellation form and the
dashboard's billing errors already did, and one test checks for all three
scripts that every dataset key they read exists on their page.
