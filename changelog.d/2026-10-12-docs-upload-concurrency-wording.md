### Fixed — the concurrency cap is per account, not per API key; the security docs say the extension picks the converter

The concurrency cap — how many requests one caller may run at the same time —
counts per account, whichever key or token the account sends, and per IP
address for a request without an account. Two texts said it was per API key:

- **The `429`** of that cap now reads "Concurrency limit reached for this
  account, or for this IP address when no account is used. Lower the
  parallelism or upgrade the plan." It used to name "this API key".
- **The pricing page** says each tier has "a concurrency cap per account (per
  IP address without an account)", in English and German, where it said
  "per-key".

The docs now describe the upload checks and the cap the way the code runs
them:

- `docs/security-overview.md` said the format "is determined from bytes". It
  now says what the vendor questionnaire says: the converter is chosen from the
  file extension, not detected from content, and the `Content-Type` the client
  sends is not used. Image uploads are then opened only by the readers for the
  supported image formats. Its magic-byte item now says that files which
  *start with* a PE, ELF, shell-script or PHP signature are rejected — the
  check reads the first bytes.
- PT-007 in `docs/security-pentest-report.md` is now **Partially addressed**,
  and the report's summary box says so: the magic-byte deny-list and the
  image-format list are in place, but the review's recommendation to check the
  content against the extension is not. Apart from images, uploads reach the
  parser their extension selects without a format check.
  `docs/security-overview.md` says the same under PT-007.
- The code anchors in `docs/security-overview.md` and `docs/threat-model.md`
  named two of the four route modules that run the `BLOCKED_MAGIC` check; they
  now name `convert.py`, `compress.py`, `pdf_pages.py` and `ai.py`.
- `docs/self-hosting.md` said `/convert` and `/compress` enforce the
  concurrency caps; the PDF tools (`/pdf/*`) and `/ai/redact/*` do too.

`tests/test_docs_match_code.py` pins this: every `BLOCKED_MAGIC` prefix is
refused with "File type not permitted." and no doc calls the list an
allow-list; every route module that takes an upload runs the check, and both
anchors name them; a JPEG under an unknown extension is refused by its
extension, while a wrong `Content-Type` changes nothing; and the `429` and both
language versions of the pricing page describe the cap the way `actor_id`
counts it.
