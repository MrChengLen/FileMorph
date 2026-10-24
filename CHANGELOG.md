# Changelog

All notable changes to FileMorph are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

> New entries go in [`changelog.d/`](changelog.d/), one file per change;
> `scripts/changelog.py` folds them in here, newest first.

---

## [1.3.0] — 2026-10-24

**Upgrading from 1.2.1.** No format or env var was removed, and no database
migration runs; `/redoc`, which rendered empty, is switched off. Every
deployment should update: this release carries the fixes for critical
advisories in the Python packages Pillow (GHSA-8g5g-8vmr-9782), certifi
(GHSA-6q48-6c7w-9gw2) and brotli (CVE-2026-111497); see the Security entries.
Still accepted until 2026-11-02, because Swagger UI does not use the options
they need: five DOMPurify advisories in the Swagger UI bundle on `/docs`, one
rated critical and one high upstream (listed in `docs/security-overview.md`).
Check before pulling:

- **Pinned to `1.2` or `1.2.1` (or their `-office` variants):** there is no
  1.2.2, so these image tags stay on 1.2.1 without the fixes. Move to `1.3`
  (or `1.3.0`); for a backport onto 1.2, write to `security@filemorph.io`.
- **New setting:** `LOCAL_TOOLS_ENABLED` (default `false`) prepares processing
  in the browser. Left off, nothing changes.
- **New refusals:** the table conversions (XLSX → CSV, CSV → XLSX,
  CSV → JSON, JSON → CSV) and PDF compression now run in a child process, as
  PDF → TXT already did, and stop after 90 seconds; on Linux the child is also
  capped at 1 GiB of address space (PDF compression: 3 GiB) and 2 GiB per file
  written (PDF compression and PDF → TXT: 1 GiB). A file past a limit gets
  `400` (`invalid_input`; PDF compression: `pdf_too_complex`) with the next
  step in the message. With pypdf 6.21 a few rare PDFs that 1.2.1 read now get
  the "could not read" message.
- **Target sizes:** a result is now at most the target, no longer up to 3 %
  (PDF: 5 %) above it. Where even the lowest quality is too big, images, and a
  PDF's embedded images, are scaled down; such results say so in
  `X-FileMorph-Warnings`, the new `X-FileMorph-Batch-Notes` header and
  `manifest.json`, which a batch ZIP now also carries when no file failed. On
  `/pdf/compress`, `X-FileMorph-Converged` now means "at most the target".
- **Messages and codes:** the limit messages no longer say "upgrade your
  plan"; they name a free account where accounts exist, or self-hosting. New
  error codes: `pdf_too_complex` and `batch_too_large`. A client that matches
  message texts needs updating.
- **Instances without accounts (no `DATABASE_URL`):** no Sign In link, and the
  account pages answer 404.
- **`APP_BASE_URL`:** the home page's curl example now targets it on every
  instance instead of filemorph.io; left at the default it shows
  `http://localhost:8000`.
- **Logs:** logged errors keep their type and traceback but no longer their
  text unless `APP_DEBUG=true`; the WeasyPrint, fontTools and pypdf loggers
  are silent; a child stopped at its CPU-time limit shows status `-9`. An
  alert rule that matched error texts needs a new pattern.
- **Image and TLS:** the image moves to the python:3.14-slim build of
  2026-10-21 (Python 3.14.8, a CA store without the compromised emSign root).
  Installed without the image, update the operating system's ca-certificates
  package: outgoing mail trusts it.

### Changed — the target size is an upper bound

Compressing to a target size no longer accepts a result up to 3 % above it
(5 % for PDFs): `/compress`, `/compress/batch` and `/pdf/compress` now return
the best quality that is at most the target, so the file fits an upload limit
of the same size. When even the lowest quality is too big, an image is scaled
down to fewer pixels, and a PDF's embedded images are scaled down (they keep
their place and size on the page), and the search runs again. The result
stays above the target only when not even an image's smallest size (short
edge 16 px, quality 1) fits — one carrying a large colour profile, say; the
image then keeps its size at quality 1 — or for a PDF whose images can't
shrink enough, for instance because its text and fonts leave too little room.

Every such result says so. `/compress` sends `X-FileMorph-Converged` and, in
`X-FileMorph-Warnings`, `resized=<w>x<h>` or `target=missed`; `/pdf/compress`
sends `scaled=<percent>`. `/compress/batch` lists the files in the new
`X-FileMorph-Batch-Notes` header and in `manifest.json`, which the ZIP now
carries whenever a file has notes; every manifest entry and the body of a 422
gained a `notes` list. The web UI shows the notes next to the result, in
English and German, and reads a size in MB as 1,000,000 bytes, rounded down,
so the result fits a limit of that size however a portal counts it.
`X-FileMorph-Converged` on `/pdf/compress` now means "at most the target": a
PDF with nothing to recompress that already fits reports `true`. The pages,
`llms.txt` and the API docs describe the upper bound instead of the 3 %
overshoot.

### Security — pypdf 6.21.2 and opentelemetry-api 1.45.1

pypdf moves from 6.19.0 to 6.21.2. That fixes the eight advisories published on
2026-10-21/22: infinite loops and unbounded memory use on crafted PDFs (seven,
moderate) and unvalidated JPEG image data (one, low). Four of the seven, an
endless loop and three memory blow-ups in reading a PDF, could be reached
through uploads to the PDF tools and PDF → TXT; the other three and the JPEG
one sit in pypdf features FileMorph does not call.
opentelemetry-api, which FastAPI pulls in, moves from 1.45.0 to 1.45.1, which
bounds the parsing of the W3C `tracestate` header (GHSA-xcq7-p3pf-p88h,
moderate). Both are floors in `requirements.txt`, so a later re-lock cannot fall
back below them; nothing else in the lockfile moved.

The new pypdf also turns away a few rare PDFs that 6.19 read. PDF → TXT now
fails on a text run with an odd number of bytes in a font with two-byte
character codes (such as Identity-H, common for embedded fonts), and on more
than two million tokens in one page's content; PDF → TXT and the PDF tools
both fail on more than 100,000 entries in one array or dictionary. Such files
now get the "could not read" message.

### Security — three DOMPurify advisories in the Swagger UI bundle accepted until 2026-11-02

Three DOMPurify advisories published on 2026-10-22 hit the copy bundled in
Swagger UI 5.33.1, which renders the API explorer on `/docs`:
GHSA-cg2g-xh64-v4q7 (critical), GHSA-mrv2-3pqr-j5jr (high) and
GHSA-c6gr-qvv4-5v3f (low). Each needs a DOMPurify option that Swagger UI does
not set (`SAFE_FOR_TEMPLATES` with DOM output, the `IN_PLACE` mode, the XHTML
parser), and the page renders only FileMorph's own OpenAPI schema. The fix,
DOMPurify 3.4.17, is in no Swagger UI release yet: 5.34.0 still bundles 3.4.16.
`scripts/check_vendor_advisories.py` therefore accepts the three until
2026-11-02, the date of the planned Swagger UI update, when they are decided
again. `docs/security-overview.md` lists them with the two accepted on
2026-10-20.

### Fixed — no sign-in links where an instance has no accounts

A Community Edition instance has no database and so no accounts, yet its
navigation offered "Sign In" and the home page's developer section "Get API
Key →". Both led to forms that could only fail: the account API answers 503
there, and the forgot-password form even reported an email it never sent.
Where an instance has no accounts:

- The navigation has no Sign In link, on desktop and mobile.
- The developer section links "How to get an API key ↗" instead of the sign-up
  form: the self-hosting guide's API Key management section, since keys come
  from the instance's key file there.
- The account pages (`/login`, `/register`, `/forgot-password`,
  `/reset-password`, `/verify-email`, `/dashboard`, `/account-deleted`,
  `/cockpit`) answer 404, as `/pricing` does where the pricing page is off.

The developer section's curl example now targets the instance itself
(`APP_BASE_URL`) instead of filemorph.io, since a key from an instance's key
file is valid only there. Copied as it was, the example sent the file to
filemorph.io.

Instances with accounts, such as filemorph.io, are unchanged.
`docs/self-hosting.md` and `docs/installation.md` describe the behaviour.

### Changed — Conversion child processes set their limits as hard limits

On Linux the child processes that run the table conversions (XLSX → CSV,
CSV → XLSX, CSV → JSON, JSON → CSV), PDF compression and PDF → TXT set their
limits on address space, CPU time, file size and core dumps as hard limits,
which the child cannot raise again without root privileges. A child that
reaches its CPU-time limit is stopped with `SIGKILL` (status `-9` in the
server log); the request gets the same `400` as for the other limits.

### Security — brotli 1.2.1: out-of-bounds write in the decoder fixed

brotli, which WeasyPrint pulls in through fonttools, moves from 1.2.0 to
1.2.1. That fixes CVE-2026-111497 (PYSEC-2026-4322, critical), published on
2026-10-22: a crafted Brotli stream could make the decoder write past its
buffer. Every deployment should update. The new version is a floor in
`requirements.txt`, so a later re-lock cannot fall back below it; nothing
else in the lockfile moved.

### Fixed — limit messages offer a free account only where accounts exist, and the batch-size error speaks German

The limit messages offered callers without an account a free one ("Register
free …"). A Community Edition instance has no database and so no accounts:
signing up answers 503, and the hint led nowhere. Where an instance has no
accounts, the messages now point every caller to self-hosting, as they already
did for account holders. This covers the file-size, output-cap, target-size and
batch-size messages of the API and the web interface's texts for them.

- The batch-size 400 of `/convert/batch` and `/compress/batch` carries
  `X-FileMorph-Error-Code: batch_too_large`. The web interface showed the
  server's English text there, on the German pages too; it now shows its own
  text in both languages, and the "Costs and limits" link where the pricing
  page is on, as for the other limit errors.
- `docs/api-usage-guide.md` and `docs/api-reference.md` describe both cases and
  list the new error code.

### Security — Pillow 13.0.0: nine decoder advisories fixed, one of them critical

Pillow is raised from 12.3.0 to 13.0.0, the first release with the fixes for
the nine advisories published on 2026-10-20 — among them a heap buffer
overflow in the JPEG decoder (GHSA-8g5g-8vmr-9782, critical) and
out-of-bounds reads in the TIFF decoder. FileMorph decodes uploaded images
with Pillow, so every deployment should update. `requirements.txt` now
requires `Pillow>=13.0.0`; the HEIF and AVIF plugins keep their versions.

### Changed — every processing button says where the work runs

Right below each tool's start button — Convert/Compress (homepage,
`/compress`, the conversion pages), the PDF tools and the redaction tool (under
the scan, which stays on screen for the apply step) — a line now says where
the file goes: "Runs via our server — files are uploaded
and deleted right after processing." ("Läuft über unseren Server – Dateien
werden hochgeladen und nach der Verarbeitung sofort gelöscht."). It is text,
not only an icon, and it reads at WCAG AA on the tool card.

The note below the tool on the homepage and the conversion pages ("Files are
processed server-side and deleted immediately after conversion.") is gone; the
hint under the button replaces it. `/compress` and the PDF tools had no such
note before.

### Changed — The log names the error type of a failed conversion child

When a table conversion, PDF compression or PDF → TXT child process fails
unexpectedly, the server log now names the child's error type (the exception
class name) at warning level, next to the generic error the route logs. As for
every logged error, the error's text stays out of the log.

### Changed — FileMorph is free: the pricing page, navigation and account texts say so

Without Stripe configured no plan can be booked, so `/pricing` no longer shows
Pro and Business as "currently not available". It shows what is free instead:
our server with fair limits (without an account up to 30 MB per file; with a
free account up to 100 MB, 10 files per request and an API key with 1,000
calls a month), self-hosting with no feature gates, and the Compliance Edition for
organizations. A short FAQ says there are no paid plans and that a change would
be announced in advance. The homepage's plan teaser becomes the same free
summary, and its FAQ no longer mentions paid hosted plans. A deployment with
Stripe configured keeps the plan cards, the comparison table and the checkout
unchanged.

- Navigation: "Self-Hosted" is now "Self-host" ("Selbst hosten"), "Enterprise"
  is "For organizations" ("Für Organisationen"), and "Register" is no longer in
  the main navigation; registering stays reachable from the login page, the
  pricing page and the developer teaser. The URLs are unchanged.
- The registration page no longer promises an upgrade path: a free account is
  for an API key and larger files.
- Terms § 8: without Stripe, a sentence says that no paid plans are offered and
  that § 8 and § 9 apply only once they are.
- `/enterprise`: the per-year price note only appears when a tier shows a price;
  with no display price configured every tier reads "on request".
- README and `COMMERCIAL-LICENSE.md`: the hosted service is described as free
  (no Pro/Business rows), and the Compliance Edition tiers are priced on request.

### Changed — limit messages name the free way past a limit instead of an upgrade

A request that hits a tier limit no longer hears "upgrade your plan": the hosted
service has no paid plan to upgrade to. Callers without an account are pointed
to a free account, as before, and now also for batches ("Register free to send
up to 10 files per request"), for target sizes above the output cap and for the
`/compress` output cap. Everyone else is pointed to self-hosting FileMorph
("Self-host FileMorph for larger files" / "for a higher cap" / "for larger
batches"). This covers the file-size, output-cap, target-size and batch-size
messages of `/convert`, `/compress` and the PDF tools, single and batch, plus
the monthly-quota 429 ("Wait until the reset, or self-host FileMorph without a
monthly limit") and the concurrency 429. The AI routes keep their wording.

- A file that is too large inside a batch now names the next step as well.
  Every route builds this message the same way.
- Web interface: the three texts for "file too large", "result too large" and
  "target size above the limit" name self-hosting for everyone and the free
  account for visitors without one. The page doesn't know the caller's tier.
  They no longer claim a conversion worked when it stopped at the cap.
  The link next to them reads "Costs and limits" ("Kosten und Grenzen") where no
  plan can be booked; with Stripe configured it stays "See plans and limits".
- The 2 GB target-size ceiling on `/pdf/compress` gets its own text, since
  neither an account nor self-hosting lifts it.
- The German texts use the informal "du" like the rest of the site (the three
  old ones were formal).
- `docs/api-usage-guide.md` and `docs/api-reference.md` quote the new messages.

### Added — Groundwork for processing files in the browser, switched off

FileMorph is preparing an engine that processes files in the browser instead
of uploading them. This change lays the groundwork and changes nothing
visible: the new setting `LOCAL_TOOLS_ENABLED` is off by default, and no page
loads the engine yet.

- With `LOCAL_TOOLS_ENABLED=true`, the app serves the engine from
  `app/static/engine/` under `/static/engine/<tree-hash>/…`. The hash is the
  git tree id of that directory, so `git rev-parse <tag>:app/static/engine`
  shows which engine a release serves (docs/self-hosting.md, "Local tools").
  The files are cached as immutable, any other hash returns a plain 404 that
  is never cached, and the files are always sent as `text/javascript`,
  whatever type the operating system maps `.js` to. For now the engine holds
  only a placeholder module.
- The Content-Security-Policy comes in three profiles, chosen per route:
  `default` (unchanged, still used by every page), `hybrid` (adds `blob:`
  images for previews) and `local` (the browser refuses fetch, XHR,
  WebSocket, beacons, form posts, plugins and frames; navigation and pop-up
  windows stay possible). Engine files always get `local`.
- `base.html` loads `auth.js` and `app.js` in a `core_scripts` block, so a
  strict page can leave them out.

### Security — Stripe calls and outgoing mail no longer trust the compromised emSign root

The certifi update fixed certifi's own CA bundle (GHSA-6q48-6c7w-9gw2). Two
other places FileMorph takes its trusted CAs from still held the emSign ECC
Root CA - G3, below which eight intermediate CAs had their keys compromised:

- **Stripe.** The Stripe SDK checks certificates against a CA file it ships
  itself, which still trusts this root and which no dependency audit covers.
  `app/core/billing.py` now points the SDK at certifi's bundle, the one
  pip-audit watches and `requirements.txt` keeps past the advisory.
  `tests/test_stripe_ca_bundle.py` pins what the SDK hands to `requests` on a
  call. This matters only where Stripe keys are configured.
- **The image's system CA store.** Outgoing mail (aiosmtplib) and anything
  else on Python's default TLS settings trust Debian's ca-certificates from
  the base image. The base image moves to the python:3.14-slim build of
  2026-10-21, whose ca-certificates 20250419+deb13u1 (DSA-6572-1) drops this
  root and the "Comodo AAA Services root". The same build brings Python
  3.14.8 and Debian's OpenSSL security update 3.5.7-1~deb13u3 (DSA-6531-1).
  The Docker PR smoke test now fails if the image's system CA store trusts
  the emSign root. Installed without the image, FileMorph's mail trusts the
  operating system's CA store: update its ca-certificates package.

pip's own copy of certifi in the image (pip 26.2.1 vendors 2026.6.17) still
holds the root. pip runs only while the image is built, and it installs only
packages whose hash matches `requirements.lock`.

### Changed — CSV → XLSX and CSV → JSON read the CSV row by row

CSV → XLSX and CSV → JSON check that the uploaded CSV is UTF-8 and then read
it row by row while they convert it, so the memory they take depends on the
longest row, not on the file's size. The output is unchanged: line endings
inside quoted cells stay as uploaded, and a leading BOM (Excel's "CSV UTF-8")
is dropped. A CSV that is not UTF-8 still gets the same `400` and message,
before anything is converted. CSV → XLSX of a very large file can still end
at the conversion's 90-second time limit.
`tests/test_isolated_conversions.py` checks that converting a CSV takes far
less memory than the file's size.

### Added — The PDF compress page names the next step for a PDF too large or complex to compress

When `/api/v1/pdf/compress` stops a PDF at its memory and time limits, it
answers `400` with a code of its own, `pdf_too_complex`, so a client can tell
this case from other input problems. The compress page (`/pdf/compress`) shows
the message in the visitor's language with a link to “Extract PDF pages”:
extract fewer pages at a time, then compress each part. A range of pages
needs far fewer steps than splitting the PDF into single pages and
compressing each one.

### Changed — Conversion child processes also limit the size of each file they write

On Linux the child processes that run the table conversions (XLSX → CSV,
CSV → XLSX, CSV → JSON, JSON → CSV), PDF compression and PDF → TXT now also
limit the size of each file they write (table conversions 2 GiB, PDF
compression and PDF → TXT 1 GiB), next to their memory and CPU-time limits. A
write past the limit ends the child, and the request gets the same `400`
whose message names the next step as for a file over the memory or time
limit.

### Security — CI checks the vendored browser code for known vulnerabilities

pip-audit and Dependabot do not see the browser code vendored under
`app/static/vendor/` (Swagger UI, Chart.js). A new CI step,
`scripts/check_vendor_advisories.py`, asks the OSV advisory database about every
package and version in `app/static/vendor/manifest.json`, plus the libraries a
file's new `bundles` field names (today DOMPurify inside the Swagger UI bundle),
and blocks the build on a finding, the same way pip-audit does. A finding passes
only when it is accepted for that version with a reason and a review date, and
it fails again once that date has passed; an OSV answer that is incomplete or
unreadable fails the step instead of passing it. The weekly `deps-latest`
workflow runs the same check. The two low-severity advisories in the DOMPurify
bundled with Swagger UI 5.33.1 are accepted until 2026-11-02, when the Swagger
UI release that fixes them is two weeks old.

### Security — certifi 2026.10.19: its CA bundle drops the compromised emSign root

certifi is raised from 2026.7.22 to 2026.10.19 (GHSA-6q48-6c7w-9gw2,
critical). Earlier versions trust the emSign ECC Root CA - G3, below which
eight intermediate CAs had their private keys compromised: whoever holds one
of those keys and sits on the network path could pose as any host to a client
that trusts the bundle. `requirements.txt` now sets `certifi>=2026.10.19`. A
re-lock keeps existing pins, so this floor is what moves certifi past the
advisory and keeps it there; no other dependency changes.

This fixes certifi itself. Its only user in FileMorph is `requests`, which
comes in through the Stripe SDK, and the Stripe SDK checked certificates
against its own CA file, which still contains this root; the entry above
points the SDK at certifi's bundle.

### Fixed — the API docs page shows the API explorer again

`/docs` rendered empty: it loaded Swagger UI from an external CDN and started it
with an inline script, and FileMorph's Content Security Policy blocks both. The
page now serves a pinned, unmodified copy of Swagger UI 5.33.1 from
`/static/vendor/` and starts it from an external script, so it works under the
unchanged policy and loads nothing from a third-party host. If the explorer
cannot load, the page links the OpenAPI schema instead of staying blank.
`/redoc`, broken the same way and linked nowhere, is switched off;
`/openapi.json` is unchanged.

Vendored browser code is now listed in `app/static/vendor/manifest.json`
(version, source, licence, SHA-256 per file); a test fails if a file changes,
appears unlisted, or carries a licence outside the allow-list. The DOMPurify
copy bundled in Swagger UI 5.33.1 has two low-severity advisories that need a
mode Swagger UI does not use; the update to a Swagger UI release with the fix
follows once that release has been out for two weeks.

### Fixed — the privacy notice names every right, the Cloudflare transfer and a 30-day log limit

The privacy notice (`/privacy`; the German text is authoritative) was missing
parts of what Art. 13, 20, 21 and 77 GDPR require, and its § 4 — where the
hosting line on the homepage has pointed since the claims correction — did not
say what Cloudflare does with a request. Now:

- **Rights:** access, rectification, erasure, restriction, data portability,
  objection and complaint, each with its article. The right to object stands
  on its own in a highlighted box (Art. 21(4) GDPR) and names the processing
  it covers. Requests are answered without undue delay, within one month
  (Art. 12(3)).
- **Supervisory authority:** the Hamburg Commissioner for Data Protection and
  Freedom of Information, with address and website; a complaint can also go
  where the reader lives or works or where the infringement took place.
- **§ 4 Hosting and connection:** Hetzner holds what FileMorph stores.
  Cloudflare, Inc. (USA) ends the encrypted connection, so it processes IP
  addresses, request data and — in transit — uploaded and converted files.
  The transfer rests on Cloudflare's EU-U.S. Data Privacy Framework
  certification (adequacy decision); the Standard Contractual Clauses in its
  DPA apply only if that lapses. Legal basis: Art. 6(1)(f) GDPR.
- **Recipients:** Zoho Corporation GmbH, the contracting entity for Germany,
  sends account emails and hosts the operator's mailbox; rare support access
  by Zoho's Indian group company is covered by the Standard Contractual
  Clauses. Stripe's contracting entity is Stripe Payments Europe, Ltd.; Stripe
  and Cloudflare process part of the data under their own responsibility;
  paid plans are not offered at present. A copy of the Standard Contractual
  Clauses is available on request.
- **The rest of Art. 13:** the legal basis for processing uploaded files
  (Art. 6(1)(b), and (f) for other people's data in a file) and for statutory
  retention (Art. 6(1)(c)), contact by email, server logs deleted after 30
  days at the latest, which data is required, no automated decisions, and why
  there is no data protection officer.
- § 2a no longer says no file content is "stored in any form": uploads sit
  on the server as temporary files while processed, and the audit log keeps
  the output's hash. § 6 names Cloudflare's `cf_clearance` cookie after a
  security check. The notice says it applies to filemorph.io; a self-hosted
  instance needs its own.
- The German text addresses the reader as "du" throughout and cites
  "Art. 6 Abs. 1 lit. …". § 2i, shown only with the redaction add-on, says
  uploads are temporary files on the server, not held in memory only.

`docs/sub-processors.md`, `docs/vendor-security-questionnaire.md`,
`docs/records-of-processing-template.md` and `docs/security-overview.md` name
the same entities and transfer bases. Like § 6, `docs/sub-processors.md`,
`docs/vendor-security-questionnaire.md` and `docs/dpa-tom-annex.md` no longer
say "no third-party CDN": the pages load nothing from another domain, but
on filemorph.io every request passes through Cloudflare.
`docs/gdpr-privacy-analysis.md` marks its April recommendation (Cloudflare
R2 storage, the federal BfDI) as superseded. `tests/test_privacy_notice.py`
pins all of it in both languages.

### Changed — Table conversions and PDF compression run in their own process with memory and time limits

XLSX → CSV, CSV → XLSX, CSV → JSON, JSON → CSV and PDF compression
(`/api/v1/pdf/compress`) run in a child process, as PDF → TXT already does:
without the server's secrets in its environment, stopped after 90 seconds,
and on Linux limited to 1 GiB of address space (PDF compression: 3 GiB). A
file over these limits gets `400` with `X-FileMorph-Error-Code: invalid_input`
(a PDF: `pdf_too_complex`) and a message naming the next step: split the
table into smaller files, or extract fewer pages of the PDF with
`/api/v1/pdf/extract` and compress them in parts. The child's temporary files
go to the request's own temp folder, which is removed with the request.
CSV → XLSX writes its rows to a temporary file instead of holding every cell
in memory, and the PDF → TXT child also gets a CPU-time limit (35 seconds).

### Fixed — logged errors keep their type and location, not their text

A logged exception now records the exception types and the traceback —
where it failed — but no longer the exceptions' texts. Those texts can quote
the uploaded file (document text, media metadata, addresses in a document's
markup), and the privacy notice says no file content is logged. This applies
to every logged exception, so database, payment and mail errors show their
type too; an `OSError` keeps its errno name (for example `[ENOSPC]`).

- ffmpeg, Ghostscript and LibreOffice errors carry the exit status; the
  tool's stderr goes into the error only with `APP_DEBUG=true`.
- The loggers of WeasyPrint, fontTools and pypdf, and library warnings
  (routed to the `py.warnings` logger), are silent: they quote refused URLs,
  font names, raw bytes of a malformed PDF object or sheet titles. A real
  failure still reaches the converter as an exception.
- uvicorn's own line for an exception that escapes past the 500 handler
  keeps its format and loses the text; uvicorn's other lines and the access
  log are unchanged.
- The PDF compressor's "skipping undecodable image" line names the error
  type only.
- With `APP_DEBUG=true` the log keeps the full texts and the library output —
  for local debugging only; `.env.example` and `docs/self-hosting.md` say so.

`tests/test_log_privacy.py` pins it: a logged failure keeps both types,
Python's chain separators and the frames but no text unless APP_DEBUG is on;
`from None` drops the context; the four loggers are silenced; uvicorn's
exception line drops the text; a malformed PDF quotes nothing into the log;
the three tools quote their stderr only with APP_DEBUG; and the refused image
URL of an HTML upload reaches no log line. `docs/vendor-security-questionnaire.md`
and `docs/dpa-tom-annex.md` name the new guard.

---

## [1.2.1] — 2026-10-19

### Security — PDF/A conversion runs Ghostscript only on a file that starts as a PDF

A PDF/A conversion now runs its Ghostscript re-render stage only when the
upload's first non-blank bytes are the `%PDF-` header. An upload that carries
the header further in, or not at all, is refused with the existing caller-safe
`400` (`invalid_input`) before that stage, so only files that present as PDFs
reach Ghostscript.

### Fixed — public pages, catalogs and docs say only what the code does

Several claims had drifted from the code, each on many surfaces at once:
the pages and both translation catalogs, `/llms.txt`, the JSON-LD, the
content modules, `README.md`, the docs and `.env.example`. Each kind of
claim is now fixed everywhere and pinned by `tests/test_public_claims.py`.

- **No DPA for self-hosting.** `/enterprise`, `/pricing` and the homepage
  promised a "signed DPA" for the self-hosted Compliance Edition, and the
  pricing table ticked the DPA only in the self-hosted column (that row is
  gone; whether a hosted plan needs one is still open). When customers
  run FileMorph on their own servers, we process no data on their behalf, so
  no DPA is needed — as `docs/dpa-template.md` §1 already said. The pages,
  README, `COMMERCIAL-LICENSE.md`, the onboarding guide and the vendor
  questionnaire now say so; the contract templates themselves are unchanged.
- **Audit-log norms.** Citations now use ISO/IEC 27001:2022 — A.8.15 for the
  audit log instead of A.12.4.1, and the 2022 numbers for the auth events,
  release signing and metadata stripping. § 39a BeurkG is gone (it concerns
  electronic certifications), and so is the "BORA §50" reference until counsel
  confirms § 50 BRAO applies. The German pages translated "tamper-evident" as
  "manipulationssicher" (tamper-proof); the chain detects edits, so it now
  reads "manipulationserkennbar".
- **Target size.** No longer called "exact" and no "±3 %": a result is
  accepted up to 3 % above the target (`tolerance=0.03`), so a 5 MB target
  can give 5.15 MB — and an image that can't get that small comes back as
  small as it gets. The homepage FAQ, `/formats`, `/compress`, `/tools`, the
  tool's target-size field, `/llms.txt` and the JSON-LD say so, and the
  homepage comparison no longer calls target-size compression "rare".
- **Hosting.** Every page that says where filemorph.io runs uses one
  sentence — server at Hetzner in the EU, connections via Cloudflare (USA) —
  linked to § 4 of the privacy policy (new anchor `#hosting`), shown only
  where the commercial pages are on (`PRICING_PAGE_ENABLED`), so a
  self-hosted instance doesn't claim filemorph.io's hosting. Meta
  descriptions, the JSON-LD and the social-preview image, which can't carry
  the link, no longer make a hosting claim; the privacy policy's redaction
  section says that uploads travel through Cloudflare like every request.
- **`/compress`** no longer says "in your browser": the files are processed on
  the server.
- **Pricing.** The audit log and signed releases are ticked for every plan.
  No plan shows more parallel requests than the server's shared pool runs at
  once (`MAX_GLOBAL_CONCURRENCY` — Business showed 6), and "10 req/min" is no
  longer listed as a plan feature: the per-minute limit is the same for every
  plan. "Free tier is live today" and "Pro & Business launch shortly" became
  "Paid plans are currently not available".
- **Smaller fixes.** The privacy policy no longer says usage is shown in the
  dashboard (there is no counter); design partners give an anonymised case
  study instead of a logo mention; `/enterprise` says the document and
  spreadsheet share of its "180+ format pairs" (13); and
  `docs/gdpr-privacy-analysis.md` no longer describes a self-service data
  export or email change — both go through privacy@filemorph.io.
- **Contrast.** The "processed server-side" note on the homepage and the
  conversion pages, and the tool's format and target-size hints, were
  about 1.95–2.5 : 1 against the page; they now use the `ink-muted` token
  (about 7.9 : 1, WCAG AA).

---

## [1.2.0] — 2026-10-19

**Upgrading from 1.1.0.** No endpoint, format or env var was removed. Check
before pulling:

- **Cloud Edition (`DATABASE_URL` set):** the app exits at start-up (status 3)
  unless `JWT_SECRET` is set, at least 32 characters long and not a published
  placeholder; `docker-compose.cloud.yml` no longer starts without it.
  `JWT_AUDIENCE` must not be empty (default `filemorph-api`). Everyone who is
  signed in signs in once more after the update. Details in the JWT and
  sign-in entries below.
- **Database:** migrations 009–013 run automatically (`alembic upgrade head`
  in the entrypoint). 013 cannot be downgraded once format-2 audit entries
  exist.
- **Behind a reverse proxy:** per-IP limits count each visitor only when
  `FORWARDED_ALLOW_IPS` covers the proxy; otherwise every visitor shares one
  budget. Besides sign-in and uploads, 1.2.0 adds per-IP limits to the PDF
  tools, the cancellation form and failed API-key attempts (see "HSTS behind
  Docker" in `docs/self-hosting.md`). The new limits on API keys, checkout and
  the billing portal count per signed-in account.
- **New refusals:** a few requests 1.1.0 processed now get an error: `413`
  for a body over 1 MB on the account, keys, billing, contact and webhook
  routes, and for an upload over `MAX_UPLOAD_SIZE_MB` sent without
  `Content-Length` (chunked); `415` for a form that names a charset other
  than UTF-8; `400` for PDF → TXT over 10 000 pages or needing more than
  30 seconds (on Linux also more than 1 GiB), and for audio or video in a
  container outside the supported list. The entries below have the details.
- **Logs:** the limiter and spam-trap lines no longer hold IP addresses (the
  access log keeps the client IP); no log holds recipient addresses, query
  strings or database statement values. A fail2ban or alert rule that
  matched them needs a new pattern.

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

### Fixed — XLSX → CSV reads cell values only; a workbook with an active chart sheet converts

XLSX → CSV now opens the workbook for its cell values only: chart sheets are
read without their charts and images, and links to other workbooks are left
unread — a CSV holds none of these. When a chart sheet is the active sheet, the
first worksheet is exported; that used to fail with a `500`. A workbook
without any worksheet gets `400` with `X-FileMorph-Error-Code: invalid_input`
and a message that names the fix. The workbook file is closed after the export, and also when reading
it fails.

### Changed — Table conversions stop at the output cap

XLSX → CSV, JSON → CSV and CSV → JSON stop writing as soon as the output
passes your tier's output cap, instead of writing the whole file first. They
answer `413` with `X-FileMorph-Error-Code: output_cap_exceeded` and "Output
too large (over the N MB cap). Split the table into smaller files and convert
them one by one …" on `/convert`, and "Output too large (over the N MB cap).
Split the table or upgrade your plan." per file on `/convert/batch`. JSON →
CSV refuses a table whose rows × columns alone can't fit before writing
anything. A conversion that fits writes the same file as before.

### Security — PDF → PDF/A removes active content from pages, annotations, form fields and bookmarks

PDF → PDF/A (`target_format=pdfa`) removes the active content PDF/A-2
forbids and the files attached to the document, its pages and annotations, on
the Ghostscript output and on the markup-only path alike:

- from the document: additional actions (`/AA`), the open action, JavaScript,
  XFA forms, attached and associated files, portfolios, alternate
  presentations, renditions and page templates;
- from every page: additional actions, presentation steps, associated files,
  and file-attachment, sound, movie, screen, 3D and rich-media annotations;
- from the other annotations: additional actions and associated files;
- from form fields and their widgets: every action, as PDF/A-2 requires;
- from links and bookmarks: every action type PDF/A-2 does not permit, and from
  a permitted one the actions chained after it and an embedded copy of the file
  it opens.

Links (URI, GoTo and the other permitted types) and page navigation stay. A
PDF with an extreme number of pages, annotations, form fields and bookmarks
(around 200,000 together) gets a `400` (`invalid_input`) instead of a
half-checked PDF/A.

The comment on Ghostscript's `-dPDFACompatibilityPolicy=1` now says what the
setting does: Ghostscript drops a feature PDF/A-2 forbids and goes on writing
PDF/A.

Tests convert PDFs without Ghostscript and check what is left: active content
on a page, its annotations, form fields (one of them reached only through its
widget) and bookmarks; an attachment a popup still points to; an annotation
list two pages share; and malformed entries, among them names that aren't
UTF-8.

### Changed — PDF → TXT extracts the text in its own process, with a time limit

PDF → TXT (`/convert`) now runs pypdf in a child Python process
(`app/converters/_pdf_text.py`). The process is stopped after 30 seconds; on
Linux it may use at most 1 GiB of memory. A PDF too large or complex for that
gets `400` (`invalid_input`) with "This PDF is too large or complex to
extract its text in one go. Extract fewer pages with /api/v1/pdf/extract and
convert them in parts." Like the other PDF tools, PDF → TXT reads at most
10 000 pages; a larger PDF gets `400` with a message naming the cap. The
child gets no application secrets, like the LibreOffice subprocess, and its
diagnostic output is discarded. Password-protected, certificate-encrypted
and unreadable PDFs keep their existing answers.

The Docker image check on pull requests now converts a PDF to text inside
the image, so the child process is tested where it runs in production.

### Changed — PDF compression leaves JPEG 2000 images as they are

PDF compress-to-target (`/api/v1/pdf/compress`) re-encodes embedded images
stored as JPEG (`/DCTDecode`, also behind a lossless filter such as ASCII85 or
Flate, as ReportLab writes them) or with the lossless filters qpdf decodes
itself (Flate, LZW, run-length, ASCII85, ASCIIHex). JPEG 2000 images now stay
as they are, and so do images over the image size limit
(`FILEMORPH_IMAGE_MAX_MEGAPIXELS`, 89 megapixels by default) and images with
longer filter chains. An image that can't be read is skipped instead of
failing the request. A losslessly stored image with a `/Decode` array (e.g.
inverted grayscale) keeps its look; it used to come out inverted.

Tests compress PDFs with a JPEG 2000 image, unreadable and damaged images, a
JPEG of another size than its dictionary declares, a doubly compressed image
and a malformed filter, each next to an ordinary JPEG, and check that only the
ordinary JPEG is re-encoded; that images over the size limit stay as they
are; that a losslessly stored image and JPEGs behind ASCII85 and Flate are
re-encoded; and that an inverted grayscale image keeps its look.

### Security — FFmpeg reads uploads only in the formats FileMorph supports

The audio and video conversions and the video compressor now open uploads
with ffmpeg limited to the demuxers of the formats FileMorph accepts: MP3,
WAV, FLAC, Ogg (incl. Opus), AAC, ASF (WMA, WMV), MP4/MOV/M4A, AVI, Matroska
(MKV, WebM) and FLV, and only as a local file. ffmpeg still recognises other
formats, but refuses to open an upload in one of them; such an upload gets
`400` with `X-FileMorph-Error-Code: invalid_input` and "Could not read this
file: it is not in one of the audio or video formats FileMorph supports.
Save it as MP4 (video) or MP3 (audio) and try again." The list covers audio
and video together, so a file whose container differs from its extension
still converts as long as the container is one of these. The list is one
constant, `INPUT_DEMUXERS` in `app/converters/_ffmpeg.py`, and every ffmpeg
call on an upload goes through `media_input()` there.

Tests build each accepted input format with ffmpeg and convert it, check
that a file in another format is refused, and check the source code for any
other way into ffmpeg.

### Security — Request size limits count the bytes that arrive

The request size limit now counts the body as it arrives, not only the
`Content-Length` header. It is `MAX_UPLOAD_SIZE_MB` (default 100 MB) per
request on the file endpoints (`/convert`, `/compress`, the PDF tools and
the AI routes), and 1 MB on every other endpoint: the account, keys,
billing, contact and Stripe webhook routes, whose JSON bodies are a few KB.
A body past its limit gets `413` ("File too large. Maximum size: N MB" on
the file endpoints, "Request too large. Maximum size: 1 MB" elsewhere); a
`Content-Length` above the limit is refused before anything is read.

The Stripe webhook refuses a request without a `stripe-signature` header
before reading its body.

The limits live in `app/core/request_limits.py`, a pure ASGI middleware
that replaces the `limit_upload_size` HTTP middleware. Its `413` answers
carry the CORS and security headers like any route's response.

### Changed — PDF tools: page selections count each page once; split stops at the output cap

- **Page selections** (`/pdf/extract`): a page selected twice now counts
  once against the 10 000-page cap. `1-10000,1-5` used to be refused with
  "You can extract at most 10,000 pages at once", although it selects
  10 000 pages. Overlapping and adjacent ranges are merged before pages are
  counted. A selection longer than 65 536 characters gets
  `400` with `invalid_page_selection` and "The page selection is too long.
  Use ranges such as 1-100 instead of listing pages one by one." (every
  page up to the cap, listed one by one, is about 49 000 characters).
- **Split** (`/pdf/split`) checks the tier output cap while it writes the
  single-page PDFs and stops with the usual `413` (`output_cap_exceeded`,
  "Output too large (over the N MB cap).") once they pass it. Each single-page PDF carries its own copy of the
  images and fonts it uses, so a split can come out larger than its input.

Tests cover repeated and adjacent ranges, a selection exactly at and just
over the length limit, and a split stopping at the cap while it writes.

### Changed — Form bodies must be UTF-8

A form body (multipart or URL-encoded) whose `Content-Type` names a charset
other than UTF-8 now gets `415` with "Form data must be UTF-8 encoded.".
Browsers and common HTTP clients send no charset there, and `charset=utf-8`
is accepted.

### Fixed — EML → PDF decodes mail text in the character sets mail uses

EML → PDF decodes text parts and encoded header words in the character set
the mail names if it is one of the character sets mail is written in:
UTF-8/16/32, ASCII, ISO-8859-x, Windows-125x, KOI8, Mac Roman, the Japanese,
Chinese and Korean mail sets, and the labels mail clients use for them
(e.g. `ISO8859-1`, `iso-8859-8-i`, `ks_c_5601-1987`). Labels that mail
clients and browsers read as a superset get the superset (US-ASCII and
ISO-8859-1 as Windows-1252, Shift_JIS as CP932, EUC-KR as CP949, GB2312 as
GBK, Big5 as CP950). Any other label is read as UTF-8, with bytes that aren't
valid UTF-8 replaced; a mail naming a character set Python doesn't know used
to fail with a `500`. A malformed charset or boundary parameter is read as
missing.

In headers, text sent as raw 8-bit bytes is read as UTF-8, also next to
encoded words; adjacent encoded words in one character set are decoded
together, so a character split across two of them stays whole; a language
tag in an encoded word is ignored; a folded line keeps its space; and a
damaged encoded word is shown as it is. A header longer than 8,192
characters is shortened and ends in `[…]`. The body is the first HTML part
of the mail's own text (attachments and attached mails don't count), else
the first plain-text part.

### Fixed — Password reset finds the account in any letter case; long passwords work again; password checks run in a worker thread

- **Forgot password** (`/api/v1/auth/forgot-password`) finds the account by
  its address, ignoring letter case, and sends the reset email after the
  response. The online cancellation (`/api/v1/billing/cancellation`)
  compares addresses the same way.
- **Passwords longer than 72 bytes** work again for registration, password
  reset and sign-in. bcrypt reads only the first 72 bytes; since bcrypt 5 it
  refuses longer input, so registration and reset with such a password
  failed with a `500`. FileMorph now passes bcrypt the first 72 bytes
  itself, which gives the same hash as before.
- **Sign-in, registration, password reset and account deletion** hash or
  check passwords in a worker thread, so a password check no longer holds
  up other requests.

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

### Security — a release's cosign command accepts only that release's image build

A security review found that the `cosign verify` command `release.yml` writes
into each release's `IMAGE_DIGEST.txt` matched the signer against
`^https://github\.com/MrChengLen/FileMorph/`. Every workflow in the repository
passes that, at every ref: an image `docker.yml` built from `main`, or from a
branch it was dispatched on, would have verified as the release, and so would
a signature from any other workflow. The command also verified the tag, which
can later be moved to another image.

- **One signer.** The command now passes `--certificate-identity
  'https://github.com/MrChengLen/FileMorph/.github/workflows/docker.yml@refs/tags/vX.Y.Z'`,
  the exact subject Sigstore writes into the certificate when `docker.yml`
  signs for that tag. Checked against the published v1.1.0 images: all ten
  signatures (slim and office) carry that subject, while a build of `main`
  (checked on `latest`) carries `…/docker.yml@refs/heads/main`, which the new
  command rejects.
- **The digest, not the tag.** It verifies
  `ghcr.io/mrchenglen/filemorph@sha256:…` when the release job resolved the
  digest, as it did for v1.1.0. Otherwise it falls back to the tag and tells
  the reader to pull the digest cosign reports, not the tag.
- **Docs.** `docs/release-signing.md`, `docs/patch-policy.md`,
  `docs/self-hosting.md` and the comment in `docker.yml` quote the same form;
  `self-hosting.md` verifies a release instead of the moving `:office` tag.
  `release-signing.md` also shows how to tie the signature to the commit the
  tag's GPG signature covers (`--certificate-github-workflow-sha`). v1.1.0's
  `IMAGE_DIGEST.txt` predates this and keeps the old command; the docs say to
  verify v1.1.0 with the new one.

`release.yml` only runs on a signed tag, so `tests/test_supply_chain_hygiene.py`
runs the step's script with sample values (digest resolved, empty and
malformed). It fails if the command widens the signer, verifies the tag
although a digest was resolved, or `docker.yml` stops signing; each of seven
simulated regressions fails it. A second guard fails if a public doc shows a
`cosign verify` that verifies a tag or does not pin the signing workflow.

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

### Changed — audit log: record hash format 2

New audit entries carry `hash_version = 2`: `record_hash` is the SHA-256 of
`v2`, the previous hash, the event type, the UTC timestamp and the canonical
payload, one per line. `app/core/audit.py` specifies it, together with
`VERIFY_CHAIN_SQL`, the same full-chain check in plain Postgres SQL for an
auditor working from a database dump. The actor column stays outside the
hash, so account deletion (Art. 17 GDPR) can clear it without breaking the
chain. Entries written earlier keep format 1 and verify as before;
`verify_chain` checks each entry with the format it names.

- **Upgrade note (deployments with a database).** Migration
  `013_audit_hash_version` adds the column with a constraint that allows
  formats 1 and 2. On Postgres it changes only the catalogue: no row is
  rewritten, and the append-only trigger does not fire. Its downgrade refuses
  once format-2 entries exist, because the older code cannot verify them.
- `occurred_at` is now stamped by the application, because the hash needs it
  before the row is written.
- `verify_chain(start_id=…)` checks a slice of the chain again: the slice's
  first row may chain from a row before it. It used to be reported as broken.
- **Guards.** `tests/test_audit_log.py` fails when a new `audit_events` column
  is neither hashed nor explicitly left out. `tests/test_audit_postgres.py`
  migrates entries from before 013 on real Postgres and checks that they still
  verify, that `VERIFY_CHAIN_SQL` agrees with `verify_chain`, and that account
  deletion still clears the actor on them. `tests/test_alembic_heads.py` fails
  when two migrations share a parent or a revision id is longer than the
  32 characters Alembic's version table holds.

### Changed — `/convert/batch` refuses a target format longer than 16 characters up front

`POST /api/v1/convert/batch` now looks at every `target_formats` value before
it processes any file. A value longer than 16 characters — no format FileMorph
knows comes close; the longest has 4 — refuses the whole batch with `422` and
"Unknown target format. GET /api/v1/formats lists the supported ones.", the
way a mismatch between the number of `files` and `target_formats` values
already does. A shorter unknown value still fails only its own file, as
before. A test checks that every registered target fits under the limit, so a
new converter with a longer format name can't be refused by the batch route
without CI noticing.

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

### Security — Pillow can't start Ghostscript; CVE-2026-106443 (WeasyPrint) not reachable

`pip-audit` began flagging `weasyprint==69.0` for CVE-2026-106443
(GHSA-r543-q48m-4c9j, HIGH, CVSS 8.8, fixed in 70.0), which turned the
required `lint-and-test` check red on `main` and on every pull request, and
held every deploy. An image reference (`<img>`, a CSS or SVG image, a data
URI) can make WeasyPrint hand PostScript to Pillow, whose EPS reader runs
Ghostscript, an external PostScript interpreter.

Every WeasyPrint render here already gets a `url_fetcher` that refuses every
URL it is asked to fetch, so no image bytes reach Pillow and the advisory
was not reachable. The new setting removes the sink itself, so it holds
whatever the fetcher contract is, and WeasyPrint 70 changes that contract:
FileMorph converts no EPS, and at startup `apply_hardening()`
(`app/core/image_hardening.py`) now marks Ghostscript as missing for Pillow,
so an EPS image fails to load without a process being started. The PDF/A
converter runs Ghostscript itself and is not affected. Tests pin the setting
and that no process starts.

CI ignores the advisory with that reasoning next to the `pip-audit` step,
and `docs/security-overview.md` lists it among the accepted advisories.
Taking the fix, WeasyPrint 70.0, needs the same `url_fetcher` port that
already holds back CVE-2026-55073.

### Security — WeasyPrint 70: the SSRF guard is ported, two advisories are fixed

WeasyPrint, which renders HTML, Markdown, email and (on the pure-Python path)
DOCX to PDF, moves from 69.0 to 70.0. That release fixes CVE-2026-55073 (an
SSRF-protection bypass) and CVE-2026-106443 (image bytes handed to Pillow
unrestricted, with Ghostscript behind it). Neither was reachable here, so CI
had ignored both with a written reason; the two `--ignore-vuln` entries and
their rows in `docs/security-overview.md` are gone.
With python-jose already replaced by PyJWT, CI's `pip-audit` now ignores
no advisory at all.

WeasyPrint 70 accepts only an object as the URL fetcher, not a function,
which is what held the upgrade back. `_deny_url_fetcher()` now returns a
fetcher that refuses every URL it is asked for, remote, `file:` and `data:`
alike, and every `weasyprint.HTML(...)` call passes a fresh one. The PDFs
come out the same: a referenced stylesheet, font, image or attachment was
never loaded before and still is not.

Tests:

- A new test renders a page that asks for a resource of each kind
  (stylesheets, `@import`, a font, images, a CSS background, an SVG image and
  an attachment, over http, `file:` and `data:`) through all four WeasyPrint
  call sites. It fails if any resource loads or a connection is attempted.
- A self-test shows that the same page does load without the guard, so the
  test above can fail.
- A check that runs on every host, Windows included, fails when a
  `weasyprint.HTML(...)` call lacks `url_fetcher=_deny_url_fetcher()`, and
  when app code passes `write_pdf()` a stylesheet, attachment or XMP
  metadata option (these read a plain file name without asking the fetcher).
- The existing HTML, email and DOCX SSRF tests now record outbound
  connections. They used to raise inside WeasyPrint, which catches that and
  renders on, so they could not fail.
- CI now fails if WeasyPrint cannot render on the test runner, instead of
  letting its tests skip unnoticed.

The requirement is now `weasyprint>=70,<71`, and Dependabot holds back
WeasyPrint 71 instead of 70, so the next major again needs a deliberate
update. On Windows, WeasyPrint 70 also looks for the GTK/Pango libraries in
`C:\msys64\ucrt64\bin` (`docs/installation.md`).

### Security — JWTs are handled by PyJWT instead of python-jose; tokens must carry exp, iss and aud

`python-jose` has had no release or commit since 3.5.0 (May 2025), and
`pip-audit` flagged two advisories in it that have no fix: CVE-2026-85394
(algorithm confusion, in python-jose itself) and PYSEC-2026-1325 (`ecdsa`,
pulled in by it). Both were accepted as not reachable. FileMorph now signs
and checks its tokens with PyJWT 2.15.1, so both `--ignore-vuln` entries are
gone from `ci.yml`, along with `ecdsa`, `rsa`, `pyasn1` and `six` in the
image.

- **Stricter check:** a token must carry `exp`, `iss` and `aud`.
  python-jose let a signed token without `aud` or `exp` through, and one
  without `exp` never expired. Every token FileMorph issues carries all
  three.
- **No sign-out:** the token format is unchanged (HS256, same secret, same
  claims). Sessions, and password-reset and verification links already
  sent, stay valid. A test pins tokens that python-jose issued. The one
  exception is a deployment that set `JWT_AUDIENCE` to an empty value:
  PyJWT treats an empty `aud` as missing and refuses every token, so give
  it a value (the default is `filemorph-api`) before upgrading.
- **Malformed tokens:** a token longer than 4096 characters, or with
  non-ASCII characters, is refused before it is parsed; the ones FileMorph
  issues are a few hundred ASCII characters. A lone surrogate character in
  the token sent to the refresh, password-reset or verification route got
  a 500; it now gets the usual 401 or 400.
- **`cryptography` stays:** pypdf needs it to open AES-encrypted PDFs, and it
  used to arrive through python-jose. It is now listed in
  `requirements.txt` in its own right.

### Security — Pillow reads image uploads only in the formats FileMorph supports

`/convert` and `/compress` (and their batch routes) now open uploaded images
with Pillow limited to the formats FileMorph accepts: JPEG (multi-picture
JPEGs from phone cameras included), PNG, WebP, GIF, BMP, TIFF, ICO,
HEIC/HEIF and AVIF. Pillow ships readers for many other formats; they are not
used on these uploads, which keeps the code that parses an uploaded image to
what the service needs. The list is one constant, `IMAGE_INPUT_FORMATS` in
`app/core/image_hardening.py`, and the image converters and compressors open
every upload through `open_image()` there.

An upload none of these readers recognises (a file that isn't an image, one
too damaged to be recognised, or one in another format) now gets `400` with
`X-FileMorph-Error-Code: invalid_input` and "Could not read the image: it is
damaged or not in a supported image format. Save it as PNG or JPEG (e.g. in
an image editor) and try again." A file that isn't an image used to get the
generic `500` ("Conversion failed. …", "Compression failed. …"); damage that
only shows while an image is decoded still does. `/convert/batch` and
`/compress/batch` report the message for the file.

Tests build each supported variant in-process (a two-frame MPO, an animated
PNG, ICO with PNG and with BMP frames, JPEG-compressed TIFF, HEIF and AVIF
among them), check that the list covers every image input the converters and
compressors accept, and check that files in five other Pillow formats are
refused without any reader outside the list being consulted.

### Security — PDF → PDF/A only processes PDFs, and runs Ghostscript with -dSAFER

PDF → PDF/A now confirms an upload is a PDF before its Ghostscript re-render
stage. It reads the file's `%PDF-` header — the one the spec defines, found
within the first 1024 bytes, so a damaged-but-repairable PDF still qualifies
and keeps its Ghostscript repair pass. A file without the header skips
Ghostscript and gets `400` with `X-FileMorph-Error-Code: invalid_input` and
"This file is not a PDF. Convert it to PDF first, then upload the PDF to create
a PDF/A.", where a file that was not a PDF used to reach the re-render stage and,
failing that, the markup pass for a generic 500. The re-render also passes
`-dSAFER` to Ghostscript explicitly (its default since gs 9.50) so the sandbox
holds regardless of the installed version's default.

Ghostscript is faked in the tests, so they hold with or without it installed: a
non-PDF never reaches the re-render call, a damaged PDF that carries the header
still does, the route answers 400 rather than 500, and `-dSAFER` is in the
command.

### Fixed — a certificate-encrypted PDF gets a 400 that says so, not a 500

A PDF encrypted with something other than a password — a certificate
(`/Adobe.PubSec`) or a DRM plug-in's own security handler — failed on every
PDF path. pypdf raises `NotImplementedError` while it opens such a file, or
one with an unsupported `/V`, `/SubFilter` or crypt-filter method, and
nothing caught it: `/pdf/extract`, `/pdf/split` and `/convert` (PDF → TXT,
PDF → PDF) answered a generic 500 and logged a traceback, and
`/convert/batch` reported "Conversion failed. Verify the file is valid."
pikepdf raises a plain
`PdfError` instead, so `/pdf/compress` told the user to verify the file and
logged a traceback, and PDF → PDF/A answered a 500; where Ghostscript is
installed (the Docker image ships it), the file reached Ghostscript, which
can't decrypt it either.

All these paths now answer `400` with a new code,
`X-FileMorph-Error-Code: pdf_encryption_unsupported`, and "This PDF is
protected with a certificate or an unsupported encryption. Remove the
protection (e.g. ask the sender for an unprotected copy) and try again."
PDF → PDF/A refuses the file before Ghostscript runs. The PDF tool pages and
the converter show the text in German or English; `/convert/batch` reports it
for the file. The two PDF libraries don't always agree on what is
unsupported: `/pdf/compress` and PDF → PDF/A (pikepdf) answer `pdf_encrypted`
for a `/SubFilter` or an unknown crypt-filter method under the standard
handler, which qpdf takes for a password problem.

`pdf_encrypted` keeps its meaning, "the PDF needs a password", because no
password opens a certificate-encrypted file; hence the separate code. Only
the opening step is guarded: there pypdf raises `NotImplementedError` only
while it reads the encryption dictionary (checked in pypdf 6.19); later the
same error means an unsupported stream filter, which has nothing to do with
encryption.

### Fixed — a PDF over the 10 000-page cap is no longer called unreadable

`/pdf/split` takes at most 10 000 pages, but it answered a longer PDF with
`invalid_pdf`, so the split page said "Could not read the PDF. Verify the file
is valid." about a file that was fine, and offered no way forward.
`/pdf/extract` answered a selection of more than 10 000 pages with
`invalid_page_selection`, so its page explained the page-number syntax instead
of the limit.

Both now answer `400` with the new `X-FileMorph-Error-Code:
pdf_too_many_pages` and a message that names the cap and the next step. The
split page says to extract up to 10 000 pages at a time and split each part,
and links to "Extract PDF pages"; the extract page says to select fewer pages
or to extract them in several parts. Both texts are in German and English. The
other codes stay as they were, and so does `/convert`: PDF → PDF over the cap
keeps `invalid_input`, whose message already names the cap.

Tests lower the cap to two pages and check the engine, both routes, a request
exactly at the cap, the localized texts and the page wiring.

### Security — office image: the LibreOffice subprocess runs without Ghostscript

On the `filemorph:office` image, DOCX→PDF conversion can delegate to a
LibreOffice (`soffice`) subprocess that parses the uploaded document. As
defense-in-depth, that subprocess now runs with a reduced environment: the
application's secrets (signing key, database URL, Stripe and SMTP credentials)
are dropped from it, and a Ghostscript stub is placed ahead of any real `gs`
on its `PATH`, so the subprocess cannot start Ghostscript.

FileMorph's own PDF/A re-render resolves Ghostscript in the app process and is
unaffected, as is the pure-Python (mammoth) conversion path. Routing tests
pin the subprocess environment (`tests/test_office_gs_isolation.py`), and the
pull-request Docker build exercises a DOCX→PDF conversion on the office image.
`docs/security-overview.md` notes it.

### Changed — dependency batch: SQLAlchemy 2.1, FastAPI 0.142 and thirteen smaller updates; Stripe 16 held back

Dependabot's weekly `python-all` group brought every pending Python update
except WeasyPrint, which stays below 70 on purpose, in one pull request, and
`requirements.lock` was recompiled once for all of them. What the image ships
now:

- **SQLAlchemy 2.1.4** (from 2.0.52). The one test that depended on 2.0
  behaviour was already made 2.1-safe in #139. 2.1.4 rather than 2.1.3
  because it fixes a connection leak and a masked error on the asyncio and
  asyncpg path FileMorph uses.
- **FastAPI 0.142.2** (from 0.141.1). It now depends on `opentelemetry-api`;
  its built-in OpenTelemetry support stays dormant unless an SDK is
  configured, and the image ships none. 0.142.2 rather than the newest patch
  release, which was younger than the three-day cooldown.
- mammoth 1.13.0 (a fix for crafted documents that took very long to convert,
  and better escaping), Markdown 3.11 (two regex-backtracking slowdowns fixed),
  uvicorn 0.54.0, pikepdf 10.16.0 and python-dotenv 1.2.4.

The floors for Pillow, pydantic, python-multipart, reportlab and the SBOM
generator rise to versions the lockfile already shipped, so nothing changes
there. Development tools: ruff 0.16.10, uv 0.12.22 (`requirements-uv.lock`
recompiled with it) and httpx 0.28.1.

Stripe stays on 15.6.1, now capped below 16. Stripe 16 pins Stripe API version
`2026-09-30.endive`, which no longer accepts `payment_method_types` when a
Checkout session is created, so Stripe would reject every checkout once keys
are set; the tests mock that call and could not notice. A new check in
`tests/test_billing_consent.py` now compares the parameters sent with the
installed SDK's Checkout contract, so such a break turns CI red. Dependabot
does not propose the upgrade until that call is ported.

### Changed — Dependabot no longer proposes the WeasyPrint 70 and Stripe 16 majors before their ports

Both majors need code changes first: WeasyPrint 70 reworks the `url_fetcher`
interface that the SSRF guard relies on, and Stripe 16 rejects a parameter the
Checkout call sends. Until now they arrived as pull requests of their own that
could only sit red until someone ported the code. Dependabot now ignores those
version ranges, like the existing caps for pikepdf and the SBOM generator, and
the port itself lifts the cap in `requirements.txt` together with the entry in
`.github/dependabot.yml`. Patch and minor releases below the caps now come in
the weekly batch instead of as pull requests of their own. A new test fails
when an ignore entry outlives its cap, so a lifted cap cannot leave the
package frozen.

### Security — assessed CVE-2026-85394 (python-jose algorithm confusion) as not reachable

`pip-audit` began flagging `python-jose==3.5.0` for CVE-2026-85394
(GHSA-3qf3-8w2g-rqmx, CRITICAL, CVSS 9.1), an incomplete fix for
CVE-2024-33663. python-jose refuses PEM- and SSH-formatted public keys as an
HMAC secret but accepts DER-encoded ones, so a service that verifies tokens
with a public key and also allows HS256 accepts a token an attacker signed
with that public key. No fixed release exists; 3.5.0 (May 2025) is the latest.

Not reachable here. FileMorph has no asymmetric key: every token is verified
in one place (`_decode` in `app/core/tokens.py`) with the symmetric
`JWT_SECRET` and `algorithms=["HS256"]`. python-jose takes the key only from
that argument, never from a `kid`, `jwk` or `jku` header, and there is no
JWKS, OIDC or SSO feature. The advisory's precondition, a public key used as
the verification key, cannot occur.

The ignore is documented at the pip-audit step in `ci.yml` and in
`docs/security-overview.md`, and is reviewed on 2026-11-05 and at each
release. Migrating off `python-jose`, which has had no commit since 3.5.0,
lifts it together with the `ecdsa` ignore (PYSEC-2026-1325).

### Fixed — licence and install docs describe the pillow-heif wheel FileMorph ships

The code review of #164 found two claims about `pillow-heif` that were already
wrong on `main`:

- **Licence.** `docs/third-party-licenses.md` and `docs/tech-stack-rationale.md`
  said the wheel's metadata declares GPLv2 and that a `pip-licenses` or SBOM
  scan will flag it. That stopped being true with pillow-heif 1.6.0, which
  dropped the `GPLv2` classifier (upstream #455): the locked 1.8.0 declares only
  `BSD-3-Clause`, and `pip-licenses` and the release SBOM
  (`cyclonedx-py environment --PEP-639`, run over the locked wheels) report
  exactly that. The GPLv2 part — the `x265` HEVC encoder the binary wheel
  bundles next to `libheif` and `libde265` — is stated only in the wheel's
  `LICENSES_bundled.txt`, which neither scan reads. The docs now say so and
  what it means for operators: running FileMorph is not distribution;
  redistributing the image or the wheel passes `x265` on under GPLv2 and
  `libheif`/`libde265` under LGPL-3.0, with their source obligations; and an
  SBOM-driven review has to add all three by hand. They also say that `x265`
  is loaded with the bundled `libheif`, although FileMorph never calls an
  encoder. The libheif row of the native-library table no longer lists
  `libaom`, which the 1.8.0 wheel does not bundle, and names the copy HEIC
  decoding uses: the wheel's (Debian's `libheif1` only in the no-wheel
  fallback).
- **libheif minimum.** pillow-heif 1.8.0 compiles only against libheif 1.23.4
  or newer (an `#error` in its C source; upstream #480). `docs/formats.md`,
  `docs/installation.md` and `README.md` sent Linux users to their
  distribution's `libheif-dev`, the pentest report said pillow-heif requires
  a system libheif (now a dated correction note there, which also says that
  dpkg-based image scanners report Debian's unused `libheif1`/`libde265-0`
  but not the bundled copies), and the Dockerfile's comments called the
  system `libheif1` the decoder pillow-heif loads. None
  of them holds: the x86_64 and aarch64 wheels bundle their own libheif, and
  a source build needs one that many distributions don't package. Debian 13
  shipped 1.19.8; 1.23.4 came as a security update (DSA-6523-1, 2026-09-28),
  which is why the Dockerfile's `libheif-dev` fallback for architectures
  without a wheel still meets that minimum. Only the Dockerfile's comments
  change; its packages, and so the image, stay the same.

Two guards in `tests/test_docs_match_code.py`: one reads the installed wheel's
licence metadata and `LICENSES_bundled.txt` and checks the licence docs
against them; the other fails when `requirements.lock` moves pillow-heif away
from the version `docs/formats.md` gives the libheif minimum for, or when two
docs quote different minimums.

### Fixed — a password-protected PDF says so, and two PDF errors stop blaming a page selection

A PDF that needs a password to open got the answer for a broken file:
"Could not read the PDF. Verify the file is valid." on `/pdf/extract`,
`/pdf/split` and `/convert` (PDF → TXT, PDF → PDF), and "PDF compression
failed. Verify your file is a valid PDF." plus a logged traceback on
`/pdf/compress`. Checking the file can't help; the password is in the way.
PDF → PDF/A was worse. Ghostscript, which runs first where it is installed (the
Docker image ships it), doesn't fail on such a file: it renders it without the
password and exits normally, so the conversion answered 200 with a PDF/A that
cannot hold the protected content. Without Ghostscript it was a 500.

pypdf raises `FileNotDecryptedError` on such a file and pikepdf
`PasswordError`; all these paths now answer `400` with
`X-FileMorph-Error-Code: pdf_encrypted` and "This PDF is password-protected.
Remove the password (e.g. open the file and print it to a new PDF) and try
again." PDF → PDF/A checks for the password before Ghostscript runs. The PDF
tool pages and the converter show the text in German or English;
`/convert/batch` reports it for the file. A PDF that opens without a password
is processed as before.

`/pdf/extract` answered a PDF without pages with `invalid_page_selection`, so
its web page asked the user to fix a page selection that was fine. It now
sends `invalid_pdf`, as `/pdf/split` already did. And `/convert` from PDF to
PDF without a page selection, which keeps every page, said "Too many pages
selected." for a document over 10 000 pages although nothing was selected;
the message now names the document's size and points to
`/api/v1/pdf/extract` for processing it in parts.

Tests build small PDFs in-process: locked with RC4-128, AES-128 and AES-256,
encrypted without an open password, without pages, and longer than a lowered
page cap. `scripts/make_testdata_pdf_error_messages.py` writes
byte-stable fixtures for checking this by hand to a gitignored local folder;
only the script ships.

### Changed — the deploy starts only for main's newest commit, once Docker and CI both passed for it

`notify-ops.yml`, which starts the deploy of filemorph.io after a merge to
`main`, used to wait for the `Docker` workflow alone, whichever commit that run
had built. The required checks are not strict and pull requests often merge
within minutes of each other, so a merge result that failed the tests could
reach production as soon as its images were built, and a deploy could pull the
image of a newer commit than the one it had checked. The deploy is now started
only when `Docker` and `CI` (lint, tests, PDF/A validation, dependency audit,
lockfile and secret scans) have both passed for the commit, and only if that
commit is still the tip of `main`, read from git when the check runs; for an
older one, the newer commit's own runs deploy. Either workflow finishing starts
the check and the run of whichever finished last goes on, so one build deploys
once. A manual `Docker` rebuild or a re-run of either workflow deploys again,
for the newest commit on `main`. The deploy pulls a moving image tag: the
dispatch now carries the commit's SHA, and pinning the deploy to it is a
follow-up on the deploy side.

The whole `CI` workflow counts, not only the required checks: while
`lockfile-drift`, which does not block a merge, or a newly published `pip-audit`
advisory keeps it red on `main`, nothing deploys, and the check says so in a
warning. Likewise, while the newest commit on `main` has not passed, an older
green one is not deployed, and neither is a commit whose `CI` run a newer merge
cancelled: the newer commit's own runs deploy instead. `docker.yml` now builds
one commit at a time per branch, so the image tags move in merge order (two
merges seconds apart used to finish out of order, as on 2026-09-26 and
2026-09-28): of several merges in a row the running build finishes, the newest
commit builds next and the ones in between are not built. Tests pin the
trigger, the job and the dispatch's body, and run the check in bash against
stand-ins for the API and `git`: a run for a pull request, a fork or another
branch never counts, a failed or empty answer is asked for again, and a tip
that cannot be read fails the step.

### Changed — veraPDF now blocks the merge, inside lint-and-test; duplicate CI runs removed

PDF/A-2b conformance now blocks the merge. The veraPDF gate ran as a workflow
of its own, `verapdf.yml`: it reported on every pull request, but nothing
required it, although the README and the pricing page call it a CI gate. Its
steps now follow the test run in `lint-and-test`, a check that merging into
`main` requires, and `verapdf.yml` is gone. The fixture is built from the
lockfile versions that job installs anyway, so the gate no longer sets up the
same environment a second time; the validator image stays pinned by digest
(`verapdf/cli` v1.30.2), now without network access and with the fixture
mounted read-only, and the fixture is still kept as an artifact, after a
failure too. A test holds both steps in that job, with no `if:` and no
`continue-on-error` to skip them.

One more duplicate and a dead trigger went. `sbom.yml` no longer runs on every push to `main`:
`docker.yml` builds the same SBOM there and attests it to the images, and the
90-day artifact the push produced had no reader. It remains a manual run that
rehearses the SBOM steps `release.yml` and `docker.yml` repeat. `ci.yml` and
`scope-guard.yml` no longer list a `develop` branch, which does not exist.

Dependabot's pip group, now `python-all`, takes every Python update instead of
only minor and patch ones. Dependabot gives a `requirements.txt` floor raise no
update type, so each still arrived as a PR of its own, #191 to #195 in one week,
and four of them turned `lint-and-test` red until `requirements.lock` was
recompiled. They now come as one weekly PR and one lockfile pass, after a
three-day cooldown. The caps on WeasyPrint (below 70), pikepdf and the SBOM
generator are held back by version range.

### Changed — changelog entries are one file each in `changelog.d/`

Every pull request used to add its entry directly under `## [Unreleased]` in
this file, the same line every time, so each merge left every other open pull
request in conflict, and a conflicting pull request gets no CI run at all.
Since 2026-09-01, 47 of 72 merged pull requests touched this file, and 22 of
them needed an extra three-commit round just to resolve that line. A
`merge=union` attribute is no way out: GitHub's server-side merges ignore it.

New entries now go in `changelog.d/<YYYY-MM-DD>-<topic>.md`, one file per
change, in the same house style; new files never conflict.
`scripts/changelog.py` folds them in here, newest first, and with
`--release X.Y.Z` it also cuts the version heading in the release-prep pull
request. `tests/test_changelog_fragments.py` checks each file's name and first
line, and fails when an entry is added at the top of this file instead. The
entries already below stay as they are and move under the next version at
release.

### Fixed — a PDF that pypdf can't read gets a 400, not a 500

pypdf raises `LimitReachedError` when a crafted file trips one of its safety
limits (declared stream length, decompressed size, font widths, page-tree
depth). It derives from `PyPdfError`, not from the `PdfReadError` the PDF paths
caught, and pypdf reads most of a file only when a page is copied or its text
is extracted, after the one guarded open. Such a file got the generic 500 and a
logged traceback instead of the 400 a broken upload gets. So did a PDF that
failed after the open with another pypdf error (in a fuzz run mostly a damaged
page object) on page extraction and splitting, and any unreadable or
password-protected PDF converted to TXT, which caught nothing. No detail
reached the client; the status and the log were wrong.

Every pypdf step that reads the upload now answers "Could not read the PDF.
Verify the file is valid." for `PyPdfError` and pypdf's plain `ValueError`s,
and logs one line naming the error's class (not its message, which can quote
the file):

- `/pdf/extract`, `/pdf/split`: `400` with `X-FileMorph-Error-Code:
  invalid_pdf`. `/pdf/extract` used to send `invalid_page_selection` for an
  unreadable file, so its web page asked the user to fix a page selection that
  was fine; an unreadable file no longer gets that code.
- `/convert` (PDF → TXT, and the PDF → PDF pass-through): `400` with
  `invalid_input`; `/convert/batch` reports the same message for that file
  instead of "Conversion failed. Verify the file is valid."

An error reading the server's own copy of the upload is now a 500 on
`/pdf/extract` and `/pdf/split` too, not a 400: pypdf reads the whole file into
memory first, so an `OSError` there is never the PDF's fault. And PDF → TXT
failed with a 500 on text containing an unpaired surrogate, which a broken font
map produces and UTF-8 can't encode; that character is now written as `?`.

Tests build tiny PDFs that fail at each stage (a page tree deeper than 100
levels, an 80 MB `/Length`, a page object without `/Type`, a font `/W` range of
100 000 glyphs, a content stream that isn't ASCII85) and check that each route
answers 400 without logging a traceback.

`scripts/make_testdata_pdf_unreadable.py` writes byte-stable fixtures for
checking this by hand (seven small PDFs, among them a password-protected one)
to a gitignored local folder; only the script ships.

### Fixed — deleting a free account works on PostgreSQL

`DELETE /api/v1/auth/account` failed with a 500 on PostgreSQL for every
account without a Stripe customer id, and nothing was deleted. Deleting the
`users` row makes Postgres null `audit_events.actor_user_id` through the
foreign key's `ON DELETE SET NULL`, which it carries out as an UPDATE, and
the audit log's append-only trigger (migration 005) refused every UPDATE, so
the whole deletion rolled back. Every account has audit events naming it —
at the latest the deletion request itself — so every such deletion failed.
Migration 012 lets exactly that change through: `actor_user_id` goes from a
value to NULL, nothing else in the row changes, and the account it named no
longer exists. Every other UPDATE or DELETE of an audit event is still
refused, including a direct UPDATE that nulls a live account's ID, and the
hash chain still verifies. Accounts with a Stripe customer id were not
affected: their `users` row is kept for the tax-retention period, so nothing
cascades.

The test suite runs on SQLite, which has no such trigger, so no test noticed.
The `lint-and-test` job and the weekly `deps-latest` run now start a
PostgreSQL 16 service, and `tests/test_audit_postgres.py` migrates an empty
database with Alembic (which surfaced the migration 001 failure below),
deletes an account through the API, and checks that its audit events are
kept without the account ID, the chain verifies, and every other change to an
event is refused. A guard fails if either workflow stops providing the
database. The TOM annex and the vendor security questionnaire name migration
012 next to 005.

### Fixed — a fresh Cloud Edition database can be migrated

On an empty PostgreSQL database, `alembic upgrade head`, which the container
entrypoint runs on every Cloud Edition start, failed in the first migration
with `type "tier_enum" already exists`: migration 001 created its two enum
types itself and then again with their tables. A fresh Cloud Edition install
therefore never started; the container kept restarting. Migration 001 now
leaves creating the types to the tables. A database that already has the
schema is not affected, since Alembic does not run migration 001 again.

### Added — online cancellation without login: "Cancel contracts here" (§ 312k BGB)

German consumer law (§ 312k BGB) requires a subscription sold online to be
cancellable online, through a button labelled "Verträge hier kündigen" that
leads straight to a confirmation page, with the cancellation confirmed by
email at once; the courts (OLG Köln 6 U 62/24, OLG Nürnberg 3 U 2214/23,
KG Berlin 5 UKl 10/25 and 5 U 6/25) hold that it must work without logging
in. Until now terms § 8 named only cancellation by email, and the dunning
email sent users to a "Manage billing" button the dashboard did not have.

- **A link on every page.** "Cancel contracts here" / „Verträge hier
  kündigen" in the footer — shown only when `STRIPE_SECRET_KEY` is set —
  opens `/cancel`, a page that holds nothing but the form (BGH I ZR 200/25:
  no alternatives on that page): the account's email address, the contract
  (Pro or Business), ordinary or extraordinary cancellation with an optional
  reason, and the end (earliest possible date, or a later one), then "Cancel
  now" / „jetzt kündigen". The site navigation is reduced there to the logo,
  the language switch and the legal links — no tools, prices or account
  links. A receipt with date and time follows, to print or save as PDF;
  navigation, footer and cookie notice are left out of every printed page
  now, so the receipt prints on its own.
- **`POST /api/v1/billing/cancellation`** — public, 10 per hour per IP, `503`
  without Stripe, and the same answer whether or not the address belongs to
  an account. An ordinary cancellation at the earliest date, for an address
  with exactly one live subscription of the named plan, is set to end with
  the billing period in Stripe (`cancel_at_period_end`); every other case —
  a later date, an extraordinary cancellation, an unknown address, another
  plan, a Stripe error — goes to the operator inbox to be handled by hand.
  The confirmation (what was declared, when it arrived, when the contract
  ends) is emailed right away — to the account's own address when one
  matches; a free-text reason is repeated in it only then, so the form
  can't carry someone else's text to a stranger's inbox. A form whose
  hidden anti-spam field is filled in is not dropped: it goes to the
  operator for review, without a Stripe change or a confirmation email,
  and the receipt says that no email went out. Two audit events record
  receipt and outcome — the email address only as a hash, no reason, no IP
  address.
- **Dashboard.** Accounts with a Stripe subscription get a "Subscription"
  card: the status, "Manage billing" — the Stripe customer portal, through
  the existing `POST /api/v1/billing/portal`, which had no caller and now
  calls Stripe off the event loop — and the cancellation link. The dunning
  email's "Manage billing" now exists.
- **Texts.** Terms § 8 names the link next to the email route; the privacy
  policy describes the processing in a new § 2g (PII redaction moves to
  § 2h); `email-setup.md`, `api-reference.md`, `.env.example`, the
  records-of-processing template, the TOM annex, the sub-processor list and
  the vendor questionnaire cover the new email and Stripe call.
- The operator inbox (`CONTACT_FORM_RECIPIENT_EMAIL` → `SMTP_REPLY_TO` →
  `SMTP_FROM_EMAIL`) is resolved in one place,
  `app/core/email.py::operator_recipient()`, for the contact form, the
  contact page and the cancellation flow.

### Fixed — the Stripe webhook failed on every real event

With stripe 15.x — the version `requirements.lock` has pinned since it was
created — `Webhook.construct_event` returns Stripe objects that are no longer
dicts, and the handlers' `.get()` raised `AttributeError`: every signed event
ended in a `500`. Paid tiers would not have been granted after checkout, a
failed payment would not have started dunning, and a cancelled subscription
would not have dropped the account to Free. The webhook now converts the
event object with `to_dict()` first. Until now the webhook tests covered only
rejected requests and the handlers were tested with plain dicts; new tests
post really signed `customer.subscription.updated`, `.deleted` and
`invoice.payment_failed` events through the route. A deployment that took
payments on an affected version should check each paying account's tier
against Stripe.

### Security — deps-lock pushes from a job that installs nothing; uv is installed hash-checked

A security review of PR #164 found (Low) that `lockfile-drift` in `ci.yml` and
the `deps-lock` workflow installed uv from PyPI by version alone, without a
hash. PyPI accepts new files for a release that is already published, and pip
takes the wheel with the most specific platform tag, so a malicious wheel added
to uv 0.12.19 later would have been installed — in `deps-lock` inside its one
job, which held `contents: write` and a checkout that kept its credentials,
right before the step that commits and pushes. Exploiting it took a compromised
uv upload to PyPI, not access to this repository.

- **Two jobs.** `compile` installs uv, recompiles `requirements.lock` and
  `requirements-sbom.lock`, hands the two files over as an artifact and then
  test-installs them, with `contents: read`, no cache and a checkout that keeps
  no credentials. `commit` holds `contents: write`, installs nothing and runs
  only GitHub's checkout and download actions. It unpacks the artifact outside
  its checkout, takes the two lockfiles out of it by name, fails if git sees
  any other change in the checkout, and commits and pushes as before.
- **Hash-checked uv.** Both jobs that compile the lockfiles now run `pip install
  --require-hashes --only-binary :all: -r requirements-uv.lock`. The new
  `requirements-uv.lock` pins the uv version `requirements-dev.txt` pins,
  0.12.19, with the hashes of all 19 files of that release; they match the
  digests PyPI publishes, and all 19 were uploaded within a minute on
  2026-09-25. The split alone would not be enough: a tampered uv in `compile`
  could not push, but it could write the lockfiles `commit` pushes.
- **What it costs.** `requirements-dev.txt` stays the one place the version is
  set, and Dependabot keeps bumping it there, but it does not edit
  `requirements-uv.lock`. A uv bump therefore fails `lint-and-test` until the
  file is regenerated with the command in `requirements-dev.txt`: red on
  purpose, where the workflows used to install whatever the new release held.
  `dependabot.yml` says so as well.
- **What the required check reads.** `lint-and-test` only checked that
  `requirements.lock` carries a hash somewhere, and its install step skips
  indented lines, which pip still reads. Every entry now has to be an exact,
  hashed pin, as in `requirements-sbom.lock` already, so an unhashed pin or an
  indented `--extra-index-url` or URL line fails the required check, not only
  `lockfile-drift`, which is not one.
- **Guards.** `tests/test_supply_chain_hygiene.py` fails if
  `requirements-uv.lock` is missing, pins anything besides uv, pins it without
  hashes, or at a different version than `requirements-dev.txt`; if a job that
  compiles a lockfile installs uv any other way, runs an action besides
  checkout, setup-python and upload-artifact, or installs or fetches anything
  except through a hash-checked `pip install`; or if `deps-lock.yml` compiles
  in a job that can push, restores a cache or keeps credentials there, lets the
  pushing job install or fetch anything or run any other action, unpacks the
  artifact inside the checkout, or takes anything but the two lockfiles out of
  it. Each of 37 simulated regressions fails at least one guard, the one-job
  `deps-lock.yml` from before this change among them.

uv 0.12.19, installed from the new file, writes both lockfiles byte for byte as
they are committed, so neither changes, and the commands recorded in their
headers, which `lockfile-drift` diffs, stay as they are.

### Fixed — after a release, `:latest` is the slim image, not the office image

`docker.yml` tags the slim image `:latest` and the office image `:office`, but
`docker/metadata-action` added a `latest` tag of its own on every release: with
its default flavor, `latest=auto`, a release tag (`vX.Y.Z` without a
pre-release part) that matches a `type=semver` entry gets `latest` as well, and
the office entries' `suffix=-office` does not apply to it. Both images were
pushed as `:latest`, and the one that finished last kept the tag — usually the
office image, the slower build. Whoever pulled `:latest` then got LibreOffice
without choosing the office image, and with the default
`FILEMORPH_OFFICE_ENGINE=auto` complex DOCX files were converted through it.
In the v1.1.0 run the office image's build and push finished 12 seconds after
the slim image's, so on 2026-06-01 `:latest` was most likely the office image
for about an hour, until the next build of `main`; if you pulled it then and
not since, pull it again. Builds of `main` were not affected. Found by the security review of
PR #180.

- **Fix.** The metadata step sets `flavor: latest=false`, so `:latest` comes
  only from the `type=raw` entry that names it for the slim image. The other
  tags stay as they were: `:office`, and `X.Y.Z`, `X.Y` and `sha-…`, each with
  `-office` on the office image. The docs already call `:latest` the slim
  image; that now holds right after a release too. `docker.yml` pushes images
  and cannot be tried before merge, so the pinned action (v6.2.0) was run
  locally on the workflow's inputs: it now tags only the slim image `latest`,
  on a release tag, a pre-release tag and `main`. The next release is the
  first real test.
- **Guard.** `tests/test_supply_chain_hygiene.py` fails if the metadata step's
  flavor is anything but `latest=false`, if another of its tag entries names
  `latest`, or if the matrix loses the unsuffixed `base` leg the `type=raw`
  entry is meant for.

### Security — urllib3 2.8.0: three advisories published on 2026-09-30

On 2026-10-01 `pip-audit` flagged urllib3 2.7.0 in `requirements.lock`, and
`lint-and-test` has failed on every CI run since. urllib3 2.8.0 fixes all three:

- CVE-2026-97687 (GHSA-8988-9cw3-xx77, High): the TLS configuration for HTTPS
  proxies could be ignored or overridden.
- CVE-2026-97689 (GHSA-vxq7-64xx-v4gw, High): `HTTPResponse.stream()` and
  `read_chunked()` could buffer a chunk-size line of unbounded length.
- CVE-2026-97688 (GHSA-gh4c-6fx4-qh6g, Medium): chunked Deflate streaming could
  enter an infinite loop.

At runtime the app uses urllib3 only through `requests`, which the Stripe SDK
uses for its API calls (pip in the base image carries a copy of its own, which
the app never runs). The lockfile now pins 2.8.0, and its two hashes match the
digests PyPI publishes. Nothing else in the lockfile changed, its header
included, and `lockfile-drift`'s command reproduces it byte for byte.

### Changed — a sign-in lasts 30 days from login

- `POST /auth/refresh` returns a new access token together with the refresh
  token it was sent, so a sign-in ends 30 days after login; without a
  database it answers `503`, like login.
- Everyone who is signed in has to sign in once more after this update.
- `docs/api-reference.md` and `docs/api-usage-guide.md` describe refresh and
  password reset; tests in `tests/test_auth_refresh.py` (new),
  `tests/test_password_reset.py` and `tests/test_upload_auth_resolution.py`.

### Fixed — patch-policy's `cosign verify` names an image tag that exists

`docs/patch-policy.md` told readers to verify the release image
`ghcr.io/mrchenglen/filemorph` under the tag `vX.Y.Z`. No such tag exists:
`docker.yml` tags a release's images with metadata-action's semver patterns,
which drop the Git tag's `v`, so release `v1.2.3` pushes the version tags
`1.2.3`, `1.2`, `1.2.3-office` and `1.2-office`. GHCR shows it for v1.1.0:
`1.1.0` resolves, `v1.1.0` is not found. The documented command therefore
failed for every release. It now names `X.Y.Z` without the `v`, like the
`filemorph:1.2.3` in `docs/release-signing.md`; its identity flags are
unchanged. `tests/test_supply_chain_hygiene.py` now fails if a public doc
names an image tag that starts with `v`, with or without the registry path in
front; run against the old text, it reports that line.

### Added — pull requests build and smoke-test both Docker images

`docker.yml` builds the images only after merge, and `notify-ops.yml` deploys
every successful main build, so a broken `Dockerfile`, `.dockerignore`,
`entrypoint.sh` or `requirements.lock` used to show up first on its way to
production. On 2026-05-26 a digest pin that BuildKit rejected (`FROM requires
either one or three arguments`) failed three main builds in a row before the
fix was merged. The new `.github/workflows/docker-pr.yml` builds the slim and
the office image on every pull request, without pushing them, and smoke-tests
each one:

- The image holds `scripts/first_run.py`, the compiled German message catalogue
  and `alembic.ini`, and not `.env`, `data/api_keys.json`, `.git`, `.github` or
  `tests/`. A `.env` and a `data/api_keys.json` are planted in the checkout
  before the build, so the check sees what `.dockerignore` does with a
  self-hoster's working folder, not only with a clean checkout. A third planted
  file, which nothing ignores, has to reach the image, so the check cannot pass
  on a build that did not use that folder.
- The container starts the way `docker-compose.yml` runs it (all capabilities
  dropped, no privilege escalation), answers `/api/v1/health` on the published
  port and prints a first-run API key. `curl` inside the container, which the
  Compose healthcheck uses, reaches it too, and it does not run as root.
- `ffmpeg` and Ghostscript run, and WeasyPrint renders a page. Start-up alone
  would not show a missing one: the converters call them only for a conversion.
- In the office image, LibreOffice converts a text file to PDF the way the DOCX
  converter calls it.

It runs on every pull request, not only on changes to the Docker files: an app
change can break the image alone, and a workflow that a `paths:` filter skips
never reports, so it could not become a required check. It is not a required
check yet.

Nothing in it can push, sign or deploy: its token is read-only and it uses no
secret. `notify-ops.yml` now also requires that the Docker run it follows was
started by a push or a manual dispatch in this repository, so a run for a pull
request never leads to a deploy. Tests pin both. A job in a workflow that
pull-request events trigger may hold neither a write token nor a secret;
`_privileged` in `tests/test_supply_chain_hygiene.py` now also recognises
`secrets['X']`, `toJSON(secrets)` and a reusable-workflow call's `secrets:`.
And `notify-ops.yml`'s condition and trigger are pinned word for word.

### Fixed — self-hosting and security docs: systemd unit, licences and release facts

The self-hosting, installation, development, security and licensing docs had
drifted from the code they describe. The systemd unit was missing `/usr/bin`
on `PATH` (ffmpeg/Ghostscript/LibreOffice invisible to a non-Docker install),
never loaded `.env` into the process environment (`DATABASE_URL`,
`FORWARDED_ALLOW_IPS` and `FILEMORPH_IMAGE_MAX_MEGAPIXELS` are read directly
from `os.environ`, not through the app's own `.env` parsing), bound
`0.0.0.0` instead of `127.0.0.1`, and ran multiple workers despite the rate
limiter and concurrency caps being per-process. Account deletion, the Stripe
webhook table and the audit-log hash paragraph described a pre-launch state
(Stripe-touched accounts refused with 409) instead of the shipped
tax-retained deletion path. `third-party-licenses.md` was missing
Ghostscript, LibreOffice, `pillow-avif-plugin` and the vendored Chart.js /
Tailwind assets, still listed `httpx` as a runtime dependency (it's dev-only),
and pointed at a scan/SBOM that predates the lockfile-parity and
SBOM-hardening work. `patch-policy.md` claimed every merge is tagged and a
release lands every 1–4 weeks; it now describes the actual two-track model
(continuous `latest`/`sha-*` builds on every merge, a `vX.Y.Z`/`X.Y.Z` tag at
the maintainer's discretion — one so far, `v1.1.0`). Smaller fixes:
`/ready` doesn't check ffmpeg (DB + tempdir only), `APP_PORT` is read only by
`run.py`, `python3.11` is no longer an installable apt package on current
Ubuntu/Debian, a Docker UID/GID mismatch on `./data` needs a `chown` not a
`chmod`, the email-setup guide's "no SMTP" behaviour is `200` + a log line
(not `503`), and the pentest report's Tailwind-CDN / inline-script claims
are corrected in place rather than silently rewritten.

### Added — the Docker images carry a signed SBOM attestation

`docker.yml` now attests the CycloneDX SBOM to each image it pushes — slim and
office, on release tags, on every build of `main` and on manual rebuilds — so
`:latest` and `:office` carry one too. Until now the SBOM was a file attached
to the release, tied to the image by nothing but its name: `release.yml` finds
the image digest only by tag, best effort, a minute after the tag push.

- **What it covers.** The Python packages the image installs from
  `requirements.lock`, at the locked versions, plus the `pip` of the virtualenv
  the SBOM is generated from. It comes from a clean install of the lockfile,
  not from scanning the image, so the Python interpreter and the Debian
  packages of the base image and of the `apt` layers (FFmpeg, Ghostscript, the
  Cairo/Pango stack, LibreOffice) are not in it. `docs/release-signing.md` says
  so next to the verification command. Images built before this change,
  v1.1.0 among them, have no attestation.
- **How.** A new `sbom` job runs `sbom.yml`'s three SBOM steps, verbatim, with
  read access only. `attest-sbom` then signs the SBOM for each image variant
  with `actions/attest` v4.2.2 — Sigstore keyless, like the cosign signature —
  bound to the digest the build step reported, stores it with the repository's
  attestations and pushes it to GHCR. That job holds `attestations: write`,
  `id-token: write` and `packages: write`, checks nothing out, installs
  nothing, logs in with the docker CLI and runs only GitHub's own actions.
  `actions/attest-sbom` has been deprecated since v4.0.0 and only wraps
  `actions/attest`, so the latter is pinned directly.
- **Verify** with `gh attestation verify` as `docs/release-signing.md` shows
  it. `--predicate-type https://cyclonedx.org/bom` is required: without it,
  `gh` accepts only SLSA provenance and the check fails. `--signer-workflow`,
  `--source-ref` and `--source-digest` pin the workflow, the tag and the
  commit whose signed tag was verified; `--owner` alone would accept an
  attestation from any repository of the account.
- **What it costs.** The images are attested once both are built, so a deploy
  from `main` starts a little later. `notify-ops` deploys only after the whole
  Docker run succeeds, so a failure in the SBOM job (PyPI) or the attestation
  (Sigstore, the attestations API, GHCR) now holds back the deploy, a manual
  redeploy included, until "Re-run failed jobs" gets through; the SBOM
  artifact is kept for a week so that the re-run needs no new build. If one
  image fails to build, neither is attested; the other stays pushed and signed.
- **Guards.** `tests/test_supply_chain_hygiene.py` keeps `docker.yml`'s SBOM
  steps identical to `sbom.yml`'s, and fails if an image variant loses its
  attestation or its own digest output, if the attestation stops naming the
  build's digest or stops going to GHCR, if either job gets an `if:` or
  `continue-on-error` (on the job or a step), if the attesting job gains an
  action, a permission or any command besides the registry login, if the SBOM
  job gains write access, a secret, a cache or kept credentials, if the two
  jobs stop agreeing on the SBOM's file name, or if the documented command
  drops `--predicate-type` or names a workflow that does not attest. Each of
  42 simulated regressions fails at least one guard.

### Fixed — compliance templates describe what the code does

The DPA template and its TOM annex, the records-of-processing template, the
vendor security questionnaire, the sub-processor list, the support framework,
both GDPR documents, the AGPL guide for public bodies and the commercial
licence agreement template claimed more than the code does in places. They
now say that the audit log names actors by account ID (an email hash only for
failed logins, duplicate registrations, reset requests and contact-form
messages), stores its payload as JSON rather than a digest, and does not record
API-key management, admin changes, batch jobs or the `/pdf/*` tools; that
`X-Output-SHA256` comes only from single-file `/convert` and `/compress`; that
the upload check is a magic-byte deny-list and the converter is chosen by file
extension, not from content; that `app/ee/` holds only PII redaction, switched
on by `AI_OPERATIONS_ENABLED` rather than a licence key; that veraPDF runs in
CI, not per request; that a
leftover temp directory can last about 70 minutes, not 10; that uvicorn's
access log is on and a TLS-terminating edge proxy sees uploads; and that the
SMTP relay also carries contact-form messages but no receipts. Hosting and
email locations, the Python version, CSP, CORS, disclosure targets and code
anchors are updated, and vulnerability reports go to `security@filemorph.io`
only (PGP key on request); v1.1.0 is named as the only release so far, along
with what its SBOM lacks, and support response times as set per agreement. The
documents no longer name an `AUDIT_RETENTION_DAYS` setting, which never
existed: the audit log has no built-in retention period, and the operator
states theirs. Data-subject requests go to `privacy@filemorph.io`, as in the
privacy policy. The TOM annex and the questionnaire gain the rate limits and
failed-key budget, the two-job release workflow with its hash-pinned SBOM
generator and `.dockerignore`; the questionnaire also covers error messages
that no longer echo library internals, and the records of processing gain the
contact form. The account-deletion design and the questionnaire note that the
code takes the paid path for any account with a Stripe customer id; audit
events lose their actor ID only on a hard delete. In the agreement template,
no VAT is charged only while §19 UStG applies; it and the AGPL guide exclude
`app/ee/` from the AGPL.

### Fixed — website texts match what the service does

The public pages were checked claim by claim against the code:

- **Terms §8** no longer quotes subscription prices (they come from the
  pricing page) and describes cancellation by email.
- **Privacy policy:** the rate-limit description is accurate (set per route,
  from 5 contact messages per hour to 120 requests per minute); the list of
  stored data adds the preferred language, the email-verification timestamp
  and per-request usage rows; sub-processor locations are corrected (Hetzner:
  a data centre in the EU; Zoho: Amsterdam and Dublin); paid plans are not
  yet available; the date is refreshed. Logging out now also removes the
  legacy `filemorph_api_key` browser entry (`auth.js`), as §6 says — a test
  in `tests/test_cookie_notice.py` pins it.
- **/pricing and /enterprise:** API access without a key, v1.1.0 as the
  tagged release, the audit log's scope, the veraPDF gate, "180+ format
  pairs" (distinct pairs, pinned by a test), support response times agreed
  per contract, and a PGP key on request.
- **/formats** limits exact target-size compression to JPEG, WebP and AVIF.
- **Dashboard:** account deletion names the 10-year tax-retention record.
- **/security** and `/.well-known/security.txt` drop the GitHub Security
  Advisories option, which is not enabled on this repository.
- The redaction page no longer calls its engine AGPL open source (`app/ee`
  is commercially licensed); the JSON-LD `featureList` adds the PDF tools
  and PDF → PDF/A.
- `tests/test_pricing_centralized.py` fails if the terms page hardcodes a
  euro price in either language.

### Security — the Docker image is built without a restored build cache

`docker.yml` restored BuildKit's GitHub Actions cache (`cache-from: type=gha`)
in the job that holds `packages: write` and the cosign signing identity, on
tag builds and on main. Every job that runs on main can write that cache,
whatever its `permissions:` say — the cache token can be read from the runner
process — and jobs there install PyPI releases that no lockfile pins, such as
`ci.yml`'s lint-and-test (the dev tools) and the weekly `deps-latest.yml`.
BuildKit reuses a cached layer without re-running its step, so a malicious
release could have planted the layer for `pip install --require-hashes -r
requirements.lock`. The image would then have carried packages no hash was
checked against and been signed all the same — and deployed from main, or
named in a release's `IMAGE_DIGEST.txt` from a tag. Found by the security
review of PR #163; it took a compromised upstream release, not an outside
push.

- **No cache on any build.** The build step sets `no-cache: true` and neither
  restores nor exports a cache, and `setup-buildx-action` gets
  `cache-binary: false`, so a buildx binary it downloads would not go through
  the cache either. Main gets no exception: its builds read main's entries
  directly and deploy. The pull-request image check (`docker-pr.yml`, added
  in PR #174) builds without the cache as well, and without a cached buildx:
  with nothing left writing the cache, what it found would be stale or
  planted, and its smoke test would pass on layers the pull request never
  built.
- **What it costs.** A warm cached build took 29 s for the slim image and 75 s
  for the office image; built cold, they take about 60 s and 110 s. Every
  build now installs the current Debian packages (ffmpeg, Ghostscript, …)
  instead of reusing a cached layer, and those layers get new digests each
  time: pulling an update downloads everything above the Python base image —
  about 300 MB compressed for the slim image, 440 MB for the office image —
  not only the layers after `COPY . .`.
- **Guards.** `tests/test_supply_chain_hygiene.py` now fails in three cases:
  a job that holds a write token or a secret restores or saves an Actions
  cache (an `actions/cache` step, or a cache input that does not switch
  caching off); `docker.yml` drops `no-cache: true`; or a buildx step in any
  workflow uses `cache-from` or `cache-to`, or sets up buildx without
  `cache-binary: false`. Each of 17 simulated regressions, a tag-only
  `no-cache` among them, fails at least one guard.

### Fixed — API docs: keys are optional, video compression and converter registration described correctly

The API reference marked every file route "Authentication: Required", and the
`/docs` page said all endpoints require the `X-API-Key` header. The file routes
(`/convert`, `/compress`, the batch, `/pdf/*` and `/ai/redact/*` routes) take a
key but don't need one: without credentials a request runs on the anonymous
tier, a key that is sent must be valid (`401`, and `429` once an IP has sent 30
rejected keys in a minute), and keys come from the dashboard or
`scripts/generate_api_key.py`. The API guide now says what an expired Bearer
token does there — the request runs anonymously instead of getting a `401` —
and tells clients to refresh before the 15 minutes are up. `docs/formats.md`
said video compression always writes MP4 with libx264; it keeps the container,
picks the codec by container (H.264, VP9 for WebM, MPEG-4 for AVI), cannot
compress FLV or WMV, and the table now gives the real quality → CRF/qscale
values. `docs/tech-stack-rationale.md` showed a `@register("src", "tgt")`
function decorator and a registry that finds new modules on its own;
converters are `BaseConverter` classes registered with `("src", "tgt")` tuples,
and a new module must be imported in `_ensure_loaded()`.

Also corrected: the middleware list in `docs/architecture.md` (every layer
now named), which attachments are optional on which edition
(SMTP serves the contact form everywhere; ffmpeg is a local program), the
rate-limiter switch for tests (`RATELIMIT_ENABLED`), the Stripe webhook events,
the licence map (Starlette, python-multipart, Pillow and email-validator
corrected, pillow-avif-plugin and prometheus-client added — checked against
the installed package metadata), phone detection in
`docs/pii-redaction.md` (`+49`/`0049` or a leading `0` only, no other country
codes), the `/ready` checks, the API-key list fields, the
checkout audit event name and the `/formats` example. Newly documented: the
`X-FileMorph-Batch-*`, `X-FileMorph-Error-Code` and `X-FileMorph-Warnings`
headers, the download-name rule, the redaction entity types, `.redacted.txt`
output and credits, and the 600-second ffmpeg time limit. A new test in
`tests/test_docs_match_code.py` fails if a doc calls the key required on a
file route or the `/docs` text says "require".

### Changed — dependency batch: pypdf 6.19.0 and pillow-heif 1.8.0 in one lock pass

Dependabot opened five PRs on 2026-09-28. Three were merged one at a time:
#158 (`python-dotenv>=1.2.3`) and #159 (`markdown>=3.10.3`) raised floors the
lockfile already met — 1.2.3 and 3.10.3 are the locked versions — and #157
(`python-minor-patch`) moved `ruff` to 0.16.9 and `uv` to 0.12.19 in
`requirements-dev.txt`. This batch supersedes the other two, #160
(`pypdf>=6.19.0`) and #161 (`pillow-heif>=1.8.0`), and recompiles the lockfile
once: exactly those two packages move (pypdf 6.16.2 -> 6.19.0, pillow-heif
1.7.0 -> 1.8.0), every other pin stays. The next image ships them; the full
suite passes against both. Both matter for a service that parses untrusted
uploads: pypdf 6.17.0–6.19.0 add six upstream limits for crafted PDFs (token
lengths, FlateDecode recovery, font `/Widths`, page labels), and pillow-heif
1.8.0 fixes a segmentation fault on HEIC files whose metadata item type is not
valid UTF-8 — HEIC decoding runs inside the server process, so such a file
could take the worker down. Neither fix comes with a published advisory.

The lockfile is compiled with `uv` 0.12.19, the version the lockfile jobs now
read from `requirements-dev.txt` themselves (#169), and `requirements-sbom.lock`
recompiles byte-identical with it. `ruff` 0.16.9 leaves every file as
formatted, so no reformat rides along.

### Fixed — README, SECURITY.md and contributor docs match the repository

The README said no release had been tagged. It now names v1.1.0 (2026-06-01),
with its SBOM and image digest, as the one release so far. It states that
PDF/A-2b, the EXIF/XMP/IPTC strip and `X-Output-SHA256` are AGPL engine
features in every edition (the Compliance Edition adds the commercial licence,
a DPA, an SLA and a liable contact), and that `app/ee/` is commercial-only. It
also covers:
- the API usage guide and release signing, now in the docs table;
- the office image for high-fidelity DOCX → PDF;
- `scripts/promote_admin.py` for the cockpit;
- the GTK/Pango (WeasyPrint) and Ghostscript that Windows source runs need;
- the `pip install` that `dev.ps1` runs on every start;
- the current homepage navigation and quick actions in the sketch.

SECURITY.md names email to security@filemorph.io as the reporting channel.
GitHub's advisory form, which it pointed to before, is not enabled on this
repository. "Supported versions" now says there is one release so far and
that fixes land on `main`. CONTRIBUTING.md (new "CI gates" section) and the PR
template list every step of the required `lint-and-test` check next to
`secret-scan` and `scope-check`:
- ruff;
- the Python-version gate;
- template classes;
- Tailwind bundle freshness;
- i18n drift;
- `pip-audit -r requirements.lock`;
- pytest against the lockfile pins.

veraPDF and `lockfile-drift` also run, but are not required. `app/ee/` files
carry the commercial SPDX header.

`.env.example` comments now match the code:
- `APP_HOST`/`APP_PORT` are read only by `run.py`.
- `APP_DEBUG` only sets the log level; `/docs` is always on.
- Without SMTP, mail is skipped and logged; there is no 503.
- `METRICS_ENABLED` also exposes the unauthenticated `/api/v1/metrics`.
- `FORWARDED_ALLOW_IPS`, `DATABASE_URL` and `FILEMORPH_IMAGE_MAX_MEGAPIXELS`
  come from the process environment only.
- `POSTGRES_PASSWORD` and `OFFICE_SUBPROCESS_TIMEOUT_SECONDS` are listed.

`app/ee/README.md` no longer refers to a non-public document.
`COMMERCIAL-LICENSE.md` no longer promises a 4-hour reaction time for the
KRITIS and air-gap variants: response times are agreed per contract.

### Added — `API_KEYS_FILE_TIER`: API keys on a self-hosted instance can run on a bigger tier

Without `DATABASE_URL` there are no accounts, so every caller of a Community
Edition instance ran on the anonymous tier — 30 MB per file, 1 file per
batch, a 90 MB output cap, 1 concurrent request per client IP — including
callers with a valid key from `data/api_keys.json`: without a database
`get_optional_user` returns `None`, and `tier_for(None)` is `anonymous`. Short
of editing `app/core/quotas.py` an operator could not change that, and the
docs did not say it: `docs/installation.md` described the Community Edition
as "anonymous + API-key auth" without the caps, `docs/self-hosting.md` did
not mention them, and `docs/api-usage-guide.md` told self-hosters to raise
`MAX_UPLOAD_SIZE_MB` "if the larger tier limits should apply", which it
could not do on its own. The caps are sized for the hosted service's server;
on a self-hosted instance the operator's hardware sets the limit.

The new setting `API_KEYS_FILE_TIER` (default `anonymous`, so nothing changes
unless an operator sets it; empty means `anonymous` too) names the tier keys
from the key file run on: `free`, `pro`, `business` or `enterprise` gives them
that tier's file size, batch size, output cap and concurrency on convert,
compress and the PDF page routes (`app/api/deps.py::caller_tier`). Accounts
keep their own tier; callers without a key — the web UI included — stay
anonymous; the AI routes keep reading the account's tier, because their
credit ledger needs an account. An unknown value stops the start-up instead
of falling back to anonymous. Keyed requests on a lifted tier get their own
per-IP concurrency slot: `actor_id(request, user, tier)` now requires the
tier, because the per-actor semaphore is rebuilt whenever its tier's cap
changes, so keyed and keyless requests alternating on one IP would otherwise
lift the cap. The file-size and output-cap messages pick their "register"
wording by tier instead of by "no account", so a lifted key is not told it
is anonymous. The first-run banners (`entrypoint.sh`, `run.py`) no longer
point to an "API Key" field in the web UI, which has none; they name the
`X-API-Key` header. Documented in `.env.example`, a new "Limits on a
Community Edition instance" section in `docs/self-hosting.md` (including how
much memory and how many parallel slots one key can take),
`docs/installation.md`, `docs/api-usage-guide.md` and
`docs/api-reference.md`; pinned by `tests/test_api_keys_file_tier.py` (the
Community Edition chain, the setting on all seven engine routes, the web-UI
and AI boundaries) and three new checks in `tests/test_docs_match_code.py`.
`scripts/make_testdata_api_keys_file_tier.py` writes byte-stable fixtures for
checking this by hand (two small pictures and a 35 MB BMP) to a gitignored
local folder; only the script ships.


### Security — the Cloud Edition refuses to start with a public or short `JWT_SECRET`

With `DATABASE_URL` set, every login is a JWT signed with `JWT_SECRET`, and
nothing checked that value. Without it the app fell back to the default in
`app/core/config.py`, which `.env.example` also set outright, and
`docker-compose.cloud.yml` filled in a placeholder of its own. Both strings are
published in this repository, so on a deployment running with either one,
anyone who knew an account's id (random, but not secret: it is readable in the
tokens and email links the app issues) could sign a valid login token for that
account. Admin routes re-read the role from the database, so a forged token
could not turn an ordinary account into an admin, but a token for an admin's
id was an admin session. Since PR #144 a self-built image no longer carries a
`.env`, which made a `docker run` without `JWT_SECRET` more likely.

- **The app stops at start-up** when `DATABASE_URL` is set and `JWT_SECRET` is
  unset, one of the two placeholders (also in quotes or with trailing spaces),
  or shorter than 32 characters. The log reads `Refusing to start`, names the
  reason and says what to set where; it never prints the secret. The process
  exits with status 3, which uvicorn and gunicorn treat as a failed start, so a
  server with several workers stops too instead of restarting them forever.
  The check runs when `app.main` is imported, so no server option can skip it,
  and `alembic`, which the entrypoint runs first, does not import it. The
  Community Edition (no `DATABASE_URL`) issues no logins and still starts
  without `JWT_SECRET`.
- **`docker-compose.cloud.yml` has no fallback any more.** Without
  `JWT_SECRET`, every `docker compose` command that includes the overlay stops
  with a message.
- **`.env.example`** leaves `JWT_SECRET` commented out, next to a command that
  generates one.
- Generating a random secret at start-up instead was rejected: each worker
  process would sign with its own, and every restart would sign everyone out.

`docs/self-hosting.md` has a new "JWT secret (Cloud Edition)" section and a
checklist item; it recommends handing the secret over in a file (`--env-file`,
systemd `EnvironmentFile=`) rather than `docker run -e` or a systemd
`Environment=` line, which every local user can read. The installation guide
and the security overview say what the check does; the API reference listed a
missing `JWT_SECRET` among the causes of a `503`, which it never was.
`tests/test_jwt_secret_guard.py` imports the app in a fresh interpreter with
and without a usable secret, and fails if the compose overlay or
`.env.example` gets a value again.

**Upgrading:** a Cloud Edition deployment that ran without its own
`JWT_SECRET`, or with a placeholder or a shorter one, will not start after this
update. Generate a secret with
`python -c "import secrets; print(secrets.token_urlsafe(32))"`, set it as
`JWT_SECRET` in `.env` or the container's environment, and start again. With
Docker Compose, set it before any command that includes
`docker-compose.cloud.yml`, `down` and `logs` too; the running container keeps
the old secret, and stays exposed if that was a placeholder, until `up -d`
succeeds. Tokens signed with the old secret stop working, so everyone has to
log in again.

If such a deployment was reachable from the internet, anyone who knew an
account's id could have acted as that account. The new secret ends those
sessions but not what they created: revoke API keys you don't recognise
(`api_keys`, by `created_at` and `last_used_at`), and check `users.role`,
`users.tier` and `users.is_active` for changes you didn't make; the app log
records admin changes as `cockpit.patch_user` and `cockpit.soft_delete`.

### Fixed — Impressum names the Wirtschafts-Identifikationsnummer; dead EU ODR link removed

The Impressum still said a Wirtschafts-Identifikationsnummer "will be added
once issued". It has been issued, and § 5 (1) Nr. 6 DDG requires stating it,
so the page now shows it (DE463352637) in both languages. The number sits
next to the translated label, not inside it. The link to the EU Online
Dispute Resolution platform is gone: the platform was shut down on
2025-07-20, so the link pointed nowhere. The § 36 VSBG statement stays. A
new test in `tests/test_public_pages_reachability.py` pins all three in both
locales, next to the existing guard that the Steuernummer is never shown.

### Fixed — the lockfile jobs no longer fall behind a uv bump

`lockfile-drift` in `ci.yml` and the `deps-lock` workflow recompile the
lockfiles with uv, and a different uv release can write the same lockfile
differently, so both are meant to run the uv that `requirements-dev.txt` pins.
They had the version typed in, though, and Dependabot only bumps
`requirements-dev.txt`, so the workflows fell behind it twice: on 0.12.13
while it moved to 0.12.16, then on 0.12.16 while it moved to 0.12.19, where
main stood until now. Both workflows now read the version from
`requirements-dev.txt` and install it as a wheel, so a bump there moves them
too, and they stop if the file has no `uv==` line (pip would take the empty
result as nothing to install and succeed). A new test in
`tests/test_supply_chain_hygiene.py` requires that line to be a bare
`uv==X.Y.Z`, and fails if any workflow pins its own uv or a job that compiles
a lockfile installs uv any other way. uv 0.12.19 writes both lockfiles byte
for byte as 0.12.16 did, so neither is recompiled.

### Security — git ignores `.env.local`, `.env.production` and the other local `.env.*` files

`.gitignore` listed `.env`, which matches only that exact name. A
`.env.local`, `.env.production` or `.env.staging` in a working folder therefore
showed up as an untracked file, and `git add -A` staged it. The pre-commit hook
blocks `.env.production*` by name, and other files only when they assign one of
the secret variables it lists. A commit created through the GitHub API
(`createCommitOnBranch`) skips local hooks altogether, and the secret scan in
CI recognises secrets by their format, not by the file they sit in. No such
file was ever committed: `.env.example` is the only `.env` file in the history.

`.env.*` now covers the variants. `!.env.example` below it exempts the
template, since the last matching line wins, so `git add` and tools that
honour `.gitignore` still see it. `tests/test_gitignore.py` asks
`git check-ignore --no-index` about `.env`, `.env.local`, `.env.production`,
`.env.staging` and the nested `app/.env` and `app/.env.local` (all ignored),
and about `.env.example` (not ignored). It accepts only a rule from the
repository's own `.gitignore`, so a global excludes file on one machine
cannot hide a regression.

### Changed — the web UI offers target-size compression for AVIF too

The server has compressed AVIF to an exact target size since AVIF support
landed, but the web UI offered "By target size" only for JPEG and WebP: with
an AVIF file selected, the option silently disappeared. The UI now offers it
for AVIF as well — `TARGET_SIZE_FORMATS` in `app/static/js/app.js` matches
the server set in `app/compressors/image.py` again, pinned by the new
`tests/test_target_size_formats_parity.py`. AVIF encoding is CPU-heavy and
the binary search re-encodes several times (measured locally on two cores:
about 7–11 s for a 4-megapixel image, about 30 s for a 12-megapixel photo),
so the target-size section shows a note when an AVIF file is selected: a
large photo can take a minute or more, so AVIF batches should stay small.
Every text that said "JPEG/WebP" now names AVIF too — the mode hint in the
tool, the homepage FAQ, `/formats`, `/compress` (title, meta description,
heading, intro, limits incl. the duration caveat, how-it-works, FAQ), the
`/tools` card, `/llms.txt` and `docs/formats.md`. Two API texts were wrong
and are fixed: the OpenAPI description of `target_size_kb` (single and
batch) and `docs/api-usage-guide.md` claimed JPEG/WebP only, although the API
already accepted AVIF; the guide's timing list and target-size example now
allow for slow AVIF encodes. Rate limit, concurrency caps and output caps are
unchanged; the API already offered AVIF target-size without a key. Also
fixed on the way: clearing the file selection hid only the quality slider,
so the compression-mode toggle and target-size section (now including the
AVIF note) stayed on screen with no file selected.
`scripts/make_testdata_avif_target_size.py` writes byte-stable fixtures for
checking this by hand (a 4- and a 12-megapixel AVIF, plus a JPEG twin) to a
gitignored local folder; only the script ships.


### Security — account, API-key and billing routes are rate-limited; failed API keys are throttled

`app/core/rate_limit.py` set `default_limits=["60/minute"]`, but slowapi only
applies those through `SlowAPIMiddleware`, which the app never installed — so
only routes with their own `@limiter.limit(...)` were limited. Stripe checkout
and portal, creating, listing and revoking API keys, `/auth/refresh`,
`/auth/me` and `/auth/account/language` had no limit at all (70 ×
`GET /api/v1/keys` → no 429). A free account could create API keys without
bound, each with a label of any length, and every checkout request writes an
audit row and calls Stripe.

The account routes now have explicit limits, counted per signed-in account
rather than per IP: checkout and portal 5/min, key creation 10/min, key
revocation 30/min, key list 120/min, email language 10/min. Per account,
because a per-IP limit would let one free account use up checkout or key
revocation for everyone behind the same IP — an office, or every visitor when
the proxy doesn't forward client IPs. Limits are checked after the
dependencies, so the token is already verified when the key is derived from
it.

Three routes are exempt on purpose, each with its reason next to the
decorator:
- The Stripe webhook: Stripe signs every delivery and retries failed ones.
- `/auth/me`: its limit would be checked only after the token check and the
  DB lookup have run, so it would protect nothing, while the web UI calls it
  on every page view and a 429 sends the dashboard to `/login`.
- `/auth/refresh`: a request costs one signature check, and the web UI signs
  the user out when a refresh fails, so junk requests exhausting a per-IP
  limit would sign out everyone behind that IP.

The dead default is gone, and the limiter now counts per route instead of per
URL, so `DELETE /api/v1/keys/<id>` has one budget whatever the id. That also
applies to the cockpit's per-user `PATCH`/`DELETE` (10/min per admin IP across
all users; it used to be per target user). slowapi no longer writes its
"ratelimit exceeded" warnings, which carry the client IP or account id, to the
log: the privacy policy promises that rate-limiter IPs stay out of the logs.

An account holds at most 25 active API keys. Beyond that, `POST /api/v1/keys`
returns `409`, and the dashboard says to revoke an unused key first — it used
to reset the button silently on any failure. Key labels are capped at 100
characters.

Failed `X-API-Key` attempts were never limited either. The key check is a
FastAPI dependency and rejects a wrong key before any route limit runs (25
random keys → 25 × 401, 0 × 429). `require_api_key` now counts rejected keys
per IP across all upload routes: the first 30 per minute get `401`, later ones
`429` with `Retry-After`. The count starts only after both the key file and
the database have said no. A valid key is therefore never refused, so a
script stuck on a revoked key can't lock out its colleagues behind the same
IP — or, where the proxy doesn't pass client IPs through, every API user at
once. Requests without a key behave as before. Keys are 256-bit random values,
so this is about telling broken clients to back off, not about guessing.

`docs/api-reference.md` now lists every API endpoint with its limit and
whether it counts per IP or per account, or with the reason it has none. It
used to claim "3–5/min" for all of `/auth/*`, although refresh, `/me` and the
email language had no limit. It also claimed 5/min for billing, which had
none, and a 60/min default that never applied. And it left out the PDF, AI
and cockpit routes. It now also says that "per IP" behind a proxy needs
`FORWARDED_ALLOW_IPS`, and, behind a CDN, the visitor's address from the CDN's
header. The API usage guide and the error table say what to do about the new
`429`: fix the key, because waiting doesn't help. Two new tests fail CI when an
API route has neither a limit nor an explicit exemption, or when the table and
the code disagree. The security
overview no longer describes a 60/min bucket. The pentest report's PT-006
gets a correction note: its "60 requests/minute" and "60 guesses/minute" never
applied.

### Security — the release job no longer runs unpinned code next to its write token

A security review of PR #146 found that `release.yml`'s single job held
`contents: write`, kept the checkout's credentials, restored the pip cache
shared with the workflows on main, and then installed the CycloneDX generator
— about thirty packages, unpinned and unhashed — between building the source
tarball and publishing it. A malicious generator release, or a cache entry
planted by code merged to main, could have replaced the tarball, forged the
SBOM or `IMAGE_DIGEST.txt`, or used the token. Release tags must be
GPG-signed, so this took a compromised upstream package or main-branch code,
not an outside push.

- **Two jobs.** `sbom` installs the image's dependency set and the generator
  and runs it with `contents: read`. `verify-and-publish` holds
  `contents: write`, installs nothing and receives the SBOM as an artifact,
  downloaded into a directory of its own so it cannot replace the tarball or
  anything else the job reads. Neither job restores a cache or keeps the
  checkout's credentials, and `sbom.yml` now runs the same way. Hashes alone
  would not make a cache safe: pip installs a wheel it once built from an
  sdist on the strength of the sdist's recorded hash. The publish step now
  fails, rather than releasing without the file, if an attachment pattern
  matches nothing.
- **Hash-pinned generator.** `sbom.yml` and `release.yml` install it from the
  new `requirements-sbom.lock` with `--require-hashes --only-binary :all:`:
  32 packages around `cyclonedx-bom` 5.5.0, wheels only, so no unhashed build
  dependency can slip in. The lockfile is compiled from
  `requirements-sbom.txt`, which Dependabot updates like `requirements.txt`.
  A lockfile that no longer satisfies it fails the required test job,
  `lockfile-drift` flags any other difference, and `deps-lock` recompiles
  both lockfiles — and, since it can push, no longer restores the pip cache.
  Dependabot leaves the major version alone: 5.5.0 is the last 5.x release,
  and 7.x no longer accepts `--PEP-639`, so that move stays deliberate.
- **Shell injection (CWE-78, low).** `release.yml` pasted the tag-derived
  image name into a shell script as `${{ }}`, and `deps-lock.yml` did the same
  with the branch name before `git push` — git allows `$(` and backticks in
  both. Both values now arrive through `env:`.
- **veraPDF** runs `verapdf/cli` pinned by digest — v1.30.2, which is what
  `latest` pointed at — instead of the moving `latest` tag. Dependabot does not
  track images in workflow scripts; the comment next to the pin says how to
  move it.
- **SBOM licences.** `cyclonedx-py` now runs with `--PEP-639`. Without it
  cyclonedx-bom 5.x ignores the `License-Expression` field, so packages that
  declare their licence only there were listed without one: 30 of the 78
  components in the SBOM built from main at `c13ed52`, FastAPI, Starlette,
  Pydantic, cryptography, Pillow, pikepdf, pypdf and uvicorn among them. With
  the flag, all 78 have one; the components and their versions are unchanged.

`release.yml` only runs on a signed tag and cannot be tried on a PR, so its
three SBOM steps are `sbom.yml`'s verbatim — and `sbom.yml` can be dispatched
on a branch. `tests/test_supply_chain_hygiene.py` fails if the two differ, and
guards the job split, the hashed wheel-only installs, the lockfile and the
commands that compile it, the absent caches and credentials,
`fail_on_unmatched_files`, the `env:` handling, the digest pin and
`--PEP-639`. Each of 28 simulated regressions fails at least one guard.

### Fixed — CI tests, and the SBOM lists, the versions the image ships

The image installs `requirements.lock`. Four workflows still installed
`requirements.txt`, whose `>=` ranges resolve to the newest releases, so what
they tested or described was not what ships.

- **Tests.** `lint-and-test` ran against whatever was newest on PyPI — that is
  how SQLAlchemy 2.1.0 failed a test on every branch while production stayed
  on 2.0.52. It now installs with the lockfile as a constraints file, so every
  runtime package is at its shipped version. The dev-only tools (pytest, ruff,
  uv, aiosqlite, …) are not in the lockfile and resolve as before; a dependency
  they share with the app stays at the locked version. The constraints are the
  lockfile's pins without their hashes, because pip turns on `--require-hashes`
  for the whole install as soon as one constraint carries a hash. A
  `requirements.txt` floor raised past the locked version (the usual
  Dependabot pip PR) now fails this job's install as well as `lockfile-drift`;
  recompiling the lockfile fixes both.
- **The early warning stays.** The unpinned run caught SQLAlchemy 2.1 before
  any lockfile bump would have pulled it in. It now runs in the new
  `deps-latest` workflow — weekly on Mondays and on demand — and gates nothing.
- **SBOM.** `sbom.yml`, and `release.yml` for the copy attached to releases,
  built the SBOM from the runner's Python after `pip install -r
  requirements.txt` plus the CycloneDX generator. The one produced for main
  at `1d7bad6` listed 106 packages against 77 in the lockfile: 19 locked
  packages at a version the image does not contain (SQLAlchemy 2.1.1 instead
  of 2.0.52), plus 28 that belong to the generator (`cyclonedx-bom` and its
  dependencies) — whose install had also downgraded `packaging` to 25.0,
  while the image ships 26.3. Both workflows now install the lockfile into a
  fresh venv exactly as the Dockerfile does, install the generator outside it,
  and point `cyclonedx-py environment` at that venv. (`cyclonedx-py requirements
  requirements.lock` reads the hashed lockfile fine, but its SBOM has no
  licence data and no dependency graph.) An SBOM from before this change can
  list extra packages and versions ahead of the image.
- **veraPDF.** The PDF/A-2b gate built its fixture with the newest pikepdf; it
  now installs the lockfile the way the image does.

`tests/test_supply_chain_hygiene.py` pins all four, so none of them can
quietly go back to the manifest.

### Fixed — `requirements.lock` caught up with three Dependabot floors; `uv` pinned alike

Dependabot raised the floors for `pikepdf` (`>=10.13.0.post1`), `aiosmtplib`
(`>=5.1.3`) and `alembic` (`>=1.20.0`) in `requirements.txt`, and the three
PRs were merged one at a time without recompiling the lockfile, so
`lockfile-drift` had been red on `main` since. Production was unaffected: the
image installs only `requirements.lock`, so it kept shipping the previous,
tested versions. The lockfile is recompiled with the command in its header;
exactly those three packages move (pikepdf 10.12.0 -> 10.13.0.post1,
aiosmtplib 5.1.2 -> 5.1.3, alembic 1.19.2 -> 1.20.0), every other pin stays.
With this recompile, the next image ships them.

Dependabot's `python-minor-patch` group (#132) moved `uv` to 0.12.16 in
`requirements-dev.txt` only, while `ci.yml`'s `lockfile-drift` job and the
`deps-lock` workflow still installed 0.12.13. Both now pin 0.12.16 as well, so
a lockfile compiled locally with the dev pin and the one the gate recompiles
come from the same resolver — the same three-place move as in the two
dependency batches below.

### Security — self-built images no longer bake in `.env`, API keys or `.git`

The runtime stage of the `Dockerfile` copies the whole build context
(`COPY . .`), and the repository had no `.dockerignore`. An image built from a
working folder therefore carried whatever lay in it: a real `.env`, which the
app then reads from `/app/.env` at start-up, plus `data/api_keys.json`, `.git`,
`.venv` and `.claude/` (CWE-538). Anyone with the image could read those files
back out of its layers, and a container started from it without a `./data`
volume accepted the builder's API keys instead of generating its own.

A new `.dockerignore` keeps secrets and local state (`.env*`, everything in
`data/` except `.gitkeep`, Compose override files), version-control, editor and
assistant state, Python environments and caches, local-only notes and the test
suite out of the build context.
`tests/test_dockerignore.py` evaluates the patterns the way Docker does and
checks both directions: those paths stay out, and every tracked file except the
dev-only ones (`tests/`, `.github/`, `.githooks/`, `.env.example`) stays in. The
Docker workflow only builds after merge, so a pattern that dropped a runtime
file would otherwise first show up as a broken image.

Images published by CI are built from a clean checkout, so they never contained
a `.env` or API keys; they did include that checkout's `.git` directory, the
test suite and the CI configuration, which are now left out as well. Images
built up to 2026-05-26 (with `actions/checkout` v4) also held the build job's
`GITHUB_TOKEN` in `.git/config`; GitHub revokes that token when the job ends,
so there is nothing to rotate.

**If you build the image yourself:** a `.env` in the build folder no longer
reaches the container through the image. Docker Compose is unaffected: it
passes `.env` at run time (`env_file`) and mounts `./data` as a volume. With
plain `docker run`, pass `--env-file .env -v "$PWD/data:/app/data"`; in Cloud
mode, make sure `JWT_SECRET` arrives, because without it the app now refuses to
start (see the `JWT_SECRET` entry above). If you pushed or shared an image
built before this change, treat the secrets in that `.env` (JWT secret,
database and SMTP passwords, Stripe keys) and any credential in its
`.git/config` as exposed, and rotate them. A container that ran such an image
with a named volume for `/app/data` copied the baked `api_keys.json` into that
volume; delete it there and restart to get a fresh key.

### Fixed — security docs named `requirements.txt` as the CVE-scan target

Since 2026-09-09 (PR #112) CI has run `pip-audit -r requirements.lock`: the
lockfile pins every direct and transitive Python dependency to an exact version
and hash, and it is what the image installs, while `requirements.txt` states
only version ranges. Four public docs kept quoting
`pip-audit -r requirements.txt` — among them the DPA's TOM annex, which a
procurement reviewer reads as a statement of fact — and several, §11.4 of the
vendor questionnaire included, said dependencies were pinned in
`requirements.txt`.

Corrected: `dpa-tom-annex.md` (supply-chain controls), `security-overview.md`
(self-hoster checklist item 5, CVE history, update cadence),
`security-pentest-report.md` (resolution status), `tech-stack-rationale.md`
and §11.4 of `vendor-security-questionnaire.md`. Self-hosters who fork are now
told to recompile `requirements.lock` and audit that, and `development.md`
says to recompile it after adding a package. Two more stale claims in the same
lists are gone: `security-overview.md` still called `pip-audit` a non-blocking
check, and it and the questionnaire listed Dependabot as "on the backlog",
although Dependabot (configured in `.github/dependabot.yml`) has opened weekly
update PRs since May. Both now also say that Dependabot does not touch the
lockfile, so a Python update reaches the image once the lockfile is
recompiled.

The two docs corrected in PR #112 each kept one inaccurate sentence.
`patch-policy.md` said the audit blocks the merge on High and Critical
findings, implying lower severities pass; `pip-audit` has no severity
threshold, so any finding fails the build until it is fixed or waived with
`--ignore-vuln`, as the Moderate CVE-2026-55073 was. §8.2 of the questionnaire
said CI blocks any drift between `requirements.txt` and the lockfile; the
`lockfile-drift` job flags drift without blocking a merge, and the sentence now
says so.

`tests/test_supply_chain_hygiene.py` now fails if `ci.yml` stops auditing the
lockfile, or if a tracked doc under `docs/` or a top-level `.md` file quotes a
`pip-audit -r` target other than `requirements.lock`.

### Removed — the Windows desktop build, which had never run

`build-desktop.yml` was meant to attach a `FileMorph-Windows.zip` (the app
bundled with PyInstaller, plus ffmpeg) to every GitHub release. It triggered on
`release: published`, but `release.yml` publishes releases with the built-in
`GITHUB_TOKEN`, and GitHub starts no workflow runs for events caused by that
token — the trap that once left v1.1.0 without its SBOM. The workflow never
ran, not even by hand, so no release ever carried the ZIP; the README's
download link for it had already been removed as dead in May 2026.

It is retired rather than repaired: the spec bundled no translations
(`locale/`), so the German interface would have shown English without a
warning, the build provided none of the GTK libraries WeasyPrint needs on
Windows to render Word, HTML, Markdown and email to PDF, and an unsigned
executable without an SBOM would have been the one unverifiable release
artifact. On Windows, FileMorph runs with Docker Desktop (`start.bat`) or from
source (`dev.ps1`). The workflow, `filemorph.spec`, `pyinstaller` and the
PyInstaller-only `.gitignore` entries are gone; the frozen-mode code in
`run.py` and `app/compat.py` stays (inert from source).

`tests/test_workflow_triggers.py` now fails CI if any workflow triggers on
`release`, so work that follows a release goes into `release.yml` itself.

### Fixed — API docs: status codes, error texts and Retry-After match the code

A second pass over the public docs, after the tier-limit fix below, found more
statements the code contradicts. Each one was checked against the route that
answers before it was changed.

- **`/formats` is rate-limited.** The API guide called it "unlimited"; it
  allows 120 requests/min per client IP, and it does not count toward the
  monthly API calls. The guide's `can_convert()` example read
  `formats["convert"]`, a key the response does not have — it now reads
  `formats["conversions"]`.
- **Batch `target_formats` needs one entry per file.** A count mismatch
  returns `422`, not `400`. The API reference said a single value applies to
  every file, and its example (three files, one target) got that `422`.
- **Error texts:** the guide quoted `"Output too large; try WebP/AVIF or
  upgrade."`; the output-cap errors read `"Output too large (N MB > M MB
  cap)."` plus a hint that differs between `/convert` and `/compress`. The
  file-size `413` is quoted as sent, too.
- **Batch manifest example:** entries carry the output file's name
  (`one.png`, not `one.jpg`) and the operation reads `convert`, not
  `convert_batch`.
- **`Retry-After`:** a `429` from the rate limiter carries none, but the
  per-tier concurrency `429`, the monthly-quota `429` and the `503` of a server
  at capacity do. The guide said no response had one, the API reference only
  the `503`. The guide's backoff example now honours the header and gives up
  on waits longer than two minutes, such as a used-up monthly quota.
- **Error bodies:** not every error is `{"detail": …}` — the rate limiter's
  `429` is `{"error": "Rate limit exceeded: 10 per 1 minute"}`, and a batch
  where every file failed returns `{"summary": …, "files": […]}`.
- **Status and header tables:** `413` also covers the tier's file and output
  caps, and the guide's status table gained `415`. `X-Output-SHA256` is only
  sent on single-file `/convert` and `/compress`, not on batch ZIPs, and
  `X-FileMorph-Achieved-Bytes` is sent by `/pdf/compress` as well.
- **Magic-byte rejections** are `400 "File type not permitted."`, not `415`
  (architecture doc and threat model). The API guide also said the check
  applies "regardless of whether a converter for that pair exists"; an
  unsupported pair fails first, with `422`.
- **Self-hosting guide:** "No rate limits" was wrong — the per-IP limits are
  route decorators that run on every instance. It now says where to change
  them.
- Code comments with old numbers (monthly quotas, the pro tier's output-cap
  headroom, the concurrency limiter's actor key, two test docstrings) now match
  `app/core/quotas.py` and `actor_id`.

`tests/test_docs_match_code.py` now also calls the routes and compares their
status codes, error messages and the manifest shape with what the docs quote,
and `tests/test_rate_limit.py` pins the rate-limit `429` itself: its body, and
no `Retry-After`.

### Fixed — `docs/formats.md` left out ICO and PDF → PDF/A

The conversion tables in `docs/formats.md` (linked from the README and from
the app's DOCX engine notice) had fallen behind the converter registry. The
Images table had no ICO row, although ICO converts to every other image format
FileMorph writes and to PDF; the HEIC / HEIF, WebP, BMP, TIFF / TIF and GIF
rows didn't list ICO as a target, although all of them convert to it; and the
Documents table had no PDF → PDF/A-2b row. The Video section also still said
every conversion uses libx264 + AAC — codecs are chosen per target container
(VP9 + Opus for WebM, MPEG-4 Part 2 + MP3 for AVI, WMV2 + WMA for WMV, H.264 +
AAC for the rest).

New tests in `tests/test_format_lists_match_registry.py` compare the tables
with the registry: for each From cell (e.g. "TIFF / TIF"), the To cells must
list exactly what the registry converts each format named there to, minus the
format itself. Rows sharing a From cell are merged, since the Documents and
Spreadsheets tables give each pair its own row and note. Every source in the
registry must appear in a table or in the Audio/Video lists, and the "any of
the above can be converted to any other format" sentence under those lists is
checked too.

### Added — QA fixture generator for the batch ZIP names

`scripts/make_testdata_batch_zip_names.py` writes byte-stable fixtures for
checking the batch-ZIP fix below by hand: three small images whose PNG names
collide, a CSV that converts to `manifest.json`, and a file with a `.jpg` name
that fails to convert. Output goes to a gitignored local folder; only the
script ships.

### Fixed — batch ZIPs could contain two files with the same name

When two files in a batch produce the same output name, the later one gets a
numeric suffix (`a.png`, `a_1.png`, `a_2.png`). The counter only knew the
original names, so a suffixed name that was already taken went into the ZIP a
second time: files that became `a.png`, `a.png` and `a_1.png` came out as
`a.png`, `a_1.png`, `a_1.png`, and unzipping could keep only one of the two
`a_1.png`. An output named `manifest.json` in a batch with a failed file
clashed the same way with the report of that name. `build_batch_zip` now
tracks every name it has written and never reuses one — the third file above
becomes `a_1_1.png`, the output named `manifest.json` becomes
`manifest_1.json` (it keeps its name when no file failed, since there is no
report then). Plain duplicates are named as before, and a failed file still
takes no name. The API guide's "Duplicate filenames" section describes the
rule and points API clients to the `X-FileMorph-Batch-Failed` header, rather
than the file name, to tell whether a report is present. New unit tests in
`tests/test_batch_zip.py`.

### Fixed — a plan change did not change the concurrency limit until a restart

How many requests a user (or, when anonymous, an IP) may run at once depends
on the plan: Free 1, Pro 3, Business 6. That limit was fixed when the server
first saw the user and kept until the next restart, so a user who upgraded
from Free to Pro still got `429` on their second parallel request, and a
downgraded user kept the higher limit. The workaround the code comment
suggested — minting a new API key — did not help, because the limit is tracked
per user, not per key. The limit is now checked on every request and follows a
plan change on the next one. Requests still running at that moment give their
slot back to the old limit, so they cannot raise the new one. Two new tests in
`tests/test_concurrency.py`.

### Fixed — docs quoted tier limits from before the pricing overhaul

The API usage guide's tier table and the API reference's monthly-quota table
still showed the limits from before the 2026-05-25 pricing overhaul (for
example free 50 MB / 5 files / 500 calls a month, pro 10,000 calls). Both now
match `app/core/quotas.py`, the source the server enforces and `/pricing`
renders.

- **Rate limits are not per tier.** The guide's "API/min" column promised paid
  tiers 60 requests/min, and its quickstart offered "higher rate limits" with an
  account. The limiter counts per client IP and per endpoint, the same for
  everyone: 10/min on `/convert` and `/compress`, 3/min on the batch endpoints.
  The guide now says so. In place of that column the table shows the per-tier
  concurrent-request cap (1 / 1 / 3 / 6 / 10), which is enforced per tier.
- **Anonymous uploads cap at 30 MB, not 20 MB.** Fixed in the API guide, the
  security overview and the vendor security questionnaire. Anonymous callers
  can also send a one-file batch; the guide said batch endpoints reject them.
- **Self-hosting guide:** Pro gets 3 concurrent requests and Business 6, not 2
  and 5.
- **Duplicate names in a batch ZIP** come out as `a.png`, `a_1.png`, `a_2.png`;
  the guide said the second file gets `_2`.
- **Monthly API calls:** a request rejected by the output cap does not count
  toward them (the guide said it did), and the PDF tools do (the API reference
  left them out). Its example `429` body now quotes Pro's 25000 calls.
- **Caps above the tier:** the guide now says that `MAX_UPLOAD_SIZE_MB`
  (default 100 MB) caps every whole request, so a self-hosted instance has to
  raise it for the larger tier limits to apply, and that past the server-wide
  concurrency cap (`MAX_GLOBAL_CONCURRENCY`) requests get `503`. The
  architecture doc gave that default as 2000 MB.

`tests/test_docs_match_code.py` reads the tier numbers back out of the markdown
and compares them with `QUOTAS`, and the duplicate-name example with
`build_batch_zip`, so the next quota change fails CI until the docs follow.

### Added — QA fixture generator for the batch error messages

`scripts/make_testdata_batch_errors.py` writes byte-stable fixtures for
checking the fix below by hand: a windows-1252 Markdown file and CSV, a JSON
object that isn't an array, and a small JPEG for a mixed batch. Output goes to
a gitignored local folder; only the script ships.

### Security — batch error messages no longer echo library internals

`/api/v1/convert/batch` and `/api/v1/compress/batch` returned the text of any
`ValueError` as the file's error message. Library exceptions are ValueErrors
too, so a Markdown file that isn't UTF-8 put the decoder's text (codec, byte,
offset) into the per-file message, the `X-FileMorph-Batch-Failures` header and
`manifest.json`; invalid JSON did the same with the parser's position
(CWE-209, low). Only the routes' own messages (e.g. "File too large …", "File
type not permitted.", "Output too large …") and hints a converter writes for
the user reach the client now. Everything else reads "Conversion failed. Verify
the file is valid." (compress: "Compression failed. …"), with the details in
the server log. The `/api/v1/pdf/*` routes already worked this way.

A Markdown, CSV or JSON file that isn't UTF-8 (Excel's default CSV export on
Windows, for one) gets a message naming the fix ("Re-save it as UTF-8 …"): per
file in a batch, and from single-file `/convert` as a `400` with
`X-FileMorph-Error-Code: invalid_input` instead of a generic `500` that API
clients would retry. The JSON → CSV hint "JSON must be a non-empty array of
objects", until now only visible in a batch, is returned the same way. A
leading byte-order mark, which Excel's "CSV UTF-8" always writes, is dropped
now instead of ending up in the first column name (CSV → JSON / XLSX) or
failing a JSON file.

### Fixed — `docker.yml` stored with CRLF line endings; CI now rejects CRLF files

`.github/workflows/docker.yml` had been stored with Windows line endings (CRLF)
since the manual-rebuild change (`f72dedc`), although `.gitattributes` pins YAML
to LF. GitHub runs the workflow either way, so nothing broke, but the next
ordinary edit would have converted all 117 lines and shown up as a whole-file
diff that hides the lines actually changed. The file is back to LF; its content
is unchanged (`git diff -w` is empty).

`.gitattributes` only normalises line endings when git itself stages a file. A
commit made through the GitHub API stores exactly the bytes it is sent, and a
file read from a Windows checkout can carry CRLF, which is how
`requirements.lock` once turned into a 3725-line diff. `tests/test_line_endings.py`
now fails CI when any tracked text file is stored with CRLF, so the next one is
caught in its own pull request rather than by whoever edits the file after it.

### Fixed — long upload names lost their file extension on download

`safe_download_name()` cut the finished download name to 200 characters, so an
upload whose name without extension ran past about 185–196 characters came
back as `….pn`, `…_pdfa.pd`, without any extension, or ending in one taken
from inside the name (`….exe`) — a file the OS could not open, or would treat
as the wrong type. Names that NFKD normalisation lengthens hit this much
sooner: a Hangul syllable becomes two or three characters (한 → 3), so Korean
file names of about 70 characters were already affected. The helper now
receives the stem and the suffix the route appends (`.png`, `_pdfa.pdf`,
`_compressed.jpg`, `_pages.zip`, `.redacted.<ext>`) separately and shortens
only the stem, after sanitising; the shortened stem no longer ends in a stray
dot or space. Convert and compress (single and batch), the PDF
extract/split/compress tools and AI redaction all pass their suffix this way.
Any name that already fit in 200 characters comes out exactly as before. New
tests send a 250-character name through each of those routes and cover the
Hangul case in `tests/test_core.py`.

### Changed — homepage shows seven quick actions; "More tools" box removed

Before a file was chosen, the homepage's tool card offered no concrete
operation — just the Convert/Compress toggle and an empty target-format
dropdown — and on the homepage the PDF tools (split, extract, compress)
appeared only as small text links in a "More tools" box below the fold (plus
the footer). This is the first visible step of surfacing operations earlier.

The tool card now shows, under the drop zone, seven secondary "chip" links
under an "Or choose directly" label — Compress PDF, JPG to PDF, Word to PDF,
Split PDF, Extract PDF pages, HEIC to JPG and Compress image (KB/MB) —
followed by an "All tools →" link. All seven point at pages that already
exist; "(KB/MB)" signals file size, not pixel dimensions. They render only on
the homepage — the same tool card is shared by `/compress` and the 12
`/convert/<pair>` pages, which would otherwise show self-links — and step
aside while files are selected, returning when the selection is cleared. The
"More tools" box is gone; its links now live in the chips and the "All tools"
link. The subline above the tool gains "PDF". Redact is no longer teased on
the homepage — it still appears in the footer and on /tools when AI
operations are enabled.

`scripts/i18n.py update` now passes `--ignore-obsolete`, so removed strings
are dropped from the catalogs instead of piling up as `#~` blocks.

### Fixed — FAQ, `/llms.txt`, JSON-LD and README listed an outdated set of formats

The homepage FAQ answer "Which file formats can I convert?" (DE and EN), the
format sentence in `/llms.txt`, the JSON-LD `featureList` and the README's
drop-zone mockup still named the formats from before HEIF, AVIF, ICO, HTML,
EML, FLV, WMV, AAC, WMA and Opus were added, so the homepage FAQ contradicted
the drop-zone caption above it. All of them now list every format
`/api/v1/formats` accepts. The README's "Supported Formats" table was missing
HTML and EML (now a row of their own, since they only convert to PDF) and PDF
as an image output. The lists stay hand-written (the FAQ answer is translated,
the README is static Markdown), and a new test compares each one with the
converter registry, so a new input format added without updating them fails CI
with the stale list named.

The JSON-LD honesty test used to reject the word "AVIF" anywhere in the feature
list — it was written before AVIF conversion existed. AVIF may now appear in a
format list in brackets; anywhere else the test still rejects it, because
automatic AVIF/WebP output routing still doesn't ship.

### Fixed — API keys created in the dashboard were rejected on every upload route

A key minted via `POST /api/v1/keys` (the dashboard) is stored only as a row in
the `api_keys` table. The gate in front of every upload route
(`require_api_key` on convert and compress plus their batch variants, the PDF
tools and AI redaction) checked only the self-host key file, so such a key got
`401 Invalid API key.` before `get_optional_user` — which did know how to
resolve it to its owner — ever ran. The documented CLI path (create a key in
the dashboard, send it as `X-API-Key`) therefore never worked. The regression
test for that path passed only because it reused the file-store test key.

The gate now accepts a key from the file store (unchanged,
`hmac.compare_digest`) or, when a database is configured, an active dashboard
key, looked up by its SHA-256 hash. The gate and `get_optional_user` share one
helper, `find_active_api_key` in `app/core/security.py`, so both apply one rule
to dashboard keys. A revoked key, or one whose owner is deactivated, is still
rejected with 401 rather than falling through to the anonymous tier; the
helper also checks `deleted_at`, the backstop the Bearer path already had.
Without `DATABASE_URL` (Community Edition) validation stays file-only. Six new
test cases in `tests/test_upload_auth_resolution.py`; the batch test now uses
a DB-only key and asserts 200, because a 401 also lacks the "tier limit" text
it used to check for. The architecture, security-overview, threat-model,
vendor-questionnaire and TOM-annex docs no longer say every key is compared in
constant time.

### Added — QA fixture generator for the format fixes

`scripts/make_testdata_format_fixes.py` writes byte-stable fixtures for
checking the fixes below by hand: a text PDF for the PDF/A download name, and
a windows-1252 `.htm` plus a UTF-8 `.html` with umlauts. Output goes to a
gitignored local folder; only the script ships.

### Fixed — `FILEMORPH_OFFICE_ENGINE` was silently ignored

The docs, the office compose overlay and the runtime error message all name
the DOCX → PDF engine variable `FILEMORPH_OFFICE_ENGINE`, but the settings class
only read `OFFICE_ENGINE`, so following the docs did nothing. Both names are
accepted now; `FILEMORPH_OFFICE_ENGINE` is the documented one and wins if both
are set in the same place, so set only one. `.env.example` lists it
(commented out, default `auto`).

The office overlay (`docker-compose.office.yml`) also pinned
`FILEMORPH_OFFICE_ENGINE=auto` under `environment:`, which Compose ranks above
the `.env` file. It no longer sets the variable, so the value in your `.env`
reaches the app under either name.

**Check your deployment:** if you set `FILEMORPH_OFFICE_ENGINE=libreoffice` or
`=mammoth` (in `.env` or the container environment), that value takes effect
with this change; until now you were running `auto`. `libreoffice` needs an
image with LibreOffice (`filemorph:office`) — on the slim image every DOCX → PDF
conversion would fail.

### Fixed — five places where the app said one thing and did another

- **PDF/A results download as `.pdf`.** `pdf → pdfa` used the target token as
  the file extension, so a converted `Vertrag.pdf` arrived as `Vertrag.pdfa`,
  which no operating system opens as a PDF. The download is now
  `Vertrag_pdfa.pdf`: PDF/A is a PDF profile, and the `_pdfa` suffix follows the
  `_compressed` / `_pages` convention for outputs that share their source's
  extension, so the archival copy doesn't collide with the original in the
  Downloads folder. Covers the single download, the batch ZIP entries and the
  browser's fallback name (used when a proxy strips `Content-Disposition`).
- **The 413 hint named a stale free-tier limit.** Anonymous uploads over the cap
  were told "Register free to upload up to 50 MB" on `/convert` and
  `/compress`, while the free tier allows 100 MB. The number is now read from
  `app/core/quotas.py`, so the hint follows the quota instead of drifting.
- **The drop zone's "Supported:" lists were incomplete.** The homepage caption
  left out AVIF, HEIF, ICO, HTML, EML, FLV, WMV, AAC, WMA and OPUS (compress
  mode: AVIF). Both lists now match `/api/v1/formats`; only the "Supported:"
  label is translated, the format names are plain text. A new test compares
  the rendered captions (DE and EN) with the live API, so a converter added
  without a caption update fails CI.
- **`/formats` filed AVIF and EML under "Other".** They now sit under Images and
  Documents; a test fails when a registered source format has no category.
- **`.htm` on `/convert/html-to-pdf` was a dead end.** The file picker offered
  `.htm`, but no converter accepted it, so the user got stuck at "Please select
  a target format". `.htm` is now an alias of HTML → PDF (same converter class,
  same SSRF-guarded `url_fetcher`) and `/api/v1/formats` lists it; a test
  checks that every extension a pair page's picker offers actually converts.
  Because `.htm` is what Word's "Save as Web Page" writes — in windows-1252 —
  HTML input that isn't UTF-8 now goes to WeasyPrint as bytes, so its
  `<meta charset>` is honoured. Until now every umlaut in such a file came out
  as `�` in a conversion reported as successful (this affected `.html` too).

### Fixed — stale Tailwind bundle rebuilt; CI now rejects a stale one

The committed bundle (`tailwind.625748cf.css`) had last been rebuilt in May,
so every utility class a template or script started using afterwards never
reached the browser — 46 of them. Visible effects on the live site: the
footer's "Popular conversions" grid stopped at three columns and had no
gaps; the homepage's self-hosting checklist (and grids on `/formats` and
`/pricing`) never went two-column; the "How it works" steps on `/compress`,
the PDF tools and `/redact` had no numbers; the converter's notice boxes
(DOCX engine notice, PDF-tools hint, conversion warnings) and the green
batch summary lost their tinted background, border and text colour; and
`bottom-0`/`inset-x-0` were missing, which is why the cookie notice needed a
positioning shim in `style.css`. The rebuild (`tailwind.8be3407b.css`) emits
all of them; the shim is removed. The only class dropped, `grid-cols-3`, is
no longer used anywhere.

Root cause: `docs/tailwind-build-setup.md` described a CI step that rebuilds
the bundle and fails on a difference, but it was never added to `ci.yml`. It
is now the `Tailwind bundle freshness gate`; a failing run attaches its own
bundle as the `tailwind-bundle-ci-built` artifact. Because CI now downloads
and runs the Tailwind CLI on every run, `scripts/build-tailwind.sh` verifies
each download against SHA-256 pins from the v3.4.17 release's
`sha256sums.txt` before it becomes executable (a mismatching binary in
`.tools/` is re-downloaded, a mismatching download is deleted), and `curl -f`
makes an HTTP error fail loudly instead of saving an error page as the binary.

Also fixed: the "Compare plans" heading on `/pricing` used `text-h-section`,
a class that does not exist (the token is `text-h-sect`), so it rendered as
plain body text.

### Fixed — metrics concurrency test runs each writer on its own connection

SQLAlchemy 2.1.0 (released 2026-09-24) turned
`test_daily_metrics.py::test_increment_is_safe_under_concurrent_callers` red on
every branch: 50 concurrent increments of one counter landed at 9 to 48. CI
installs `requirements.txt` unpinned, so it picked 2.1.0 up by itself; the
image installs `requirements.lock`, so production is still on 2.0.52.

The cause was the test harness, not `app/core/metrics.py`. The test ran its 50
sessions on the module's shared in-memory engine, whose `StaticPool` hands
every session the same connection — so all writers shared one transaction, and
since 2.1's aiosqlite adapter one session's pool-return rollback can land
between another's `UPDATE` and `COMMIT` and discard it. On 2.0.x the same
harness ran all 50 writes in one transaction with a single commit, so it never
exercised concurrent writers at all. Production never shares a connection
between sessions. The test now uses a file database with `NullPool`, so each
session has a real connection and the SQLite busy timeout serialises the
writers; it passes on 2.0.x and 2.1.0, still fails a non-atomic read-then-write
implementation, and checks the log first so a lock timeout fails as itself.
No version cap needed.

### Changed — dependency batch (supersedes five Dependabot PRs)

`mammoth>=1.12.1`, `pillow-heif>=1.7.0`, `stripe>=15.6.1`, `python-docx>=1.2.0`,
`ruff==0.16.7`, `uv==0.12.13`. Batched so the lockfile recompiles once and the
deploy happens once instead of five times.

Only `pillow-heif` moved in the lockfile (1.6.0 -> 1.7.0). Worth noting that
its constraint had read `>=0.15.0` while the resolved version was already on
the 1.x line — the bump to `>=1.7.0` corrects a floor that had drifted far
below what actually ships, rather than introducing a major upgrade. The 11 HEIC
tests pass.

As before, the `uv` pin is moved in all three places it appears
(`requirements-dev.txt` and the two workflows that recompile the lockfile);
Dependabot only edits the first, and a mismatch reddens the drift gate with no
dependency change behind it.

### Security — assessed CVE-2026-55073 (WeasyPrint SSRF bypass) as not reachable

`pip-audit` began flagging `weasyprint==69.0` for CVE-2026-55073
(GHSA-jf6q-chmf-3h3v, MODERATE, CVSS 6.2, `AV:L`), fixed in 70.0. The advisory
describes an SSRF-protection bypass in the very mechanism FileMorph relies on:
two `write_pdf()` channels build a fresh default `URLFetcher` instead of the
document's, so a restrictive `url_fetcher` is silently ignored.

Not reachable here. The bypass exists only for the `xmp_metadata=[url]` and
`stylesheets=[url]` parameters, and all four `write_pdf()` call sites pass the
output path alone (`app/converters/document.py` lines 228, 392, 426, 491). The
advisory's third precondition — forwarding an attacker-influenced URL into
either parameter — cannot occur.

Taking the fix is blocked by the same API change that the `<70` cap exists for:
70.0 turns `url_fetcher` from a callable into an object, which breaks
`_deny_url_fetcher`. The ignore is documented at the pip-audit step in `ci.yml`
and at the cap in `requirements.txt`, both pointing at the port that lifts it.

### Changed — dependency batch (supersedes five Dependabot PRs)

`fastapi>=0.141.1`, `uvicorn[standard]>=0.52.4`, `alembic>=1.19.2`,
`ruff==0.16.6`, `uv==0.12.10`, and the base-image digest. Batched into one
change so the lockfile is recompiled once and the deploy happens once rather
than five times. Only `alembic` actually moved in the lockfile (1.19.1 ->
1.19.2); the other constraints were already satisfied by the pinned versions.

The `uv` pin lives in three places — `requirements-dev.txt` and the two
workflows that recompile the lockfile — and Dependabot only updates the first.
All three are moved together here; a mismatch would turn the drift gate red
with no dependency change behind it.

### Added — informational cookie notice (no consent dialog) + TDDDG citation refresh

FileMorph needs no cookie banner: the app sets zero HTTP cookies (verified in
code and against production response headers), loads no third-party resources,
and until this change wrote `localStorage` only for signed-in sessions — all
consent-exempt under § 25 Abs. 2 Nr. 2 TDDDG / Art. 5(3) ePrivacy. Instead of a consent dialog
(nothing to consent to; an Accept/Reject pair would be misleading), first-time
visitors now get a dismissible informational bar
(`partials/cookie_notice.html` + `cookie-notice.js`, CSP-safe, no inline JS)
stating exactly that and deep-linking `/privacy#cookies`. The dismissal is
remembered per browser in `localStorage` (`fm_cookie_notice_dismissed` — a
cookie would contradict the claim), so the bar appears exactly once; its
fixed-bottom rule lives in `style.css` because the committed Tailwind build
lacks `bottom-0`/`inset-x-0`. The privacy policy documents the new key, and
all legal citations move from the renamed TTDSG to TDDDG (renamed May 2024,
§ 25 unchanged) across `privacy.html` and both compliance docs; the vendor
questionnaire's incorrect "session cookies (Cloud features)" line now
correctly says localStorage JWTs. New regression guards:
`test_no_set_cookie_on_public_pages` pins the zero-cookie promise,
`tests/test_cookie_notice.py` pins presence, dismiss wiring, per-locale
privacy deep link, and DE/EN texts.

### Added — deterministic QA fixture generator for manual test rounds

`scripts/make_testdata_ia_rework.py` generates seed-stable photo-like image
fixtures (large JPEG, small WebP, PNG) for hands-on testing of the target-size
compressor; output goes to a gitignored local folder, only the script ships.

### Changed — /compress review follow-ups (honest title, no-JS correctness)

The `/compress` page title no longer binds video to exact-target-size
compression (now "Compress a JPEG/WebP to a target size" / „JPEG/WebP auf
Zielgröße verkleinern" — video is quality-based, as the page copy already
said), and the embedded tool's Compress toggle is server-rendered active on
`/compress`, so the page is correct even before/without JavaScript. Plus a
README clause with the same video/target-size precision.

### Fixed — one Python version, and a lockfile that is actually installed

Two problems, one root cause: nothing compared the places where a version is
written down.

**Python.** Dependabot bumped the base image from `python:3.12-slim` to
`python:3.14-slim` on 2026-05-26 (`2b26b49`) — two minor versions in a single
"deps" commit. Nothing carried the change into the workflows, so for three
months CI tested 3.12 while production ran 3.14, and `requirements.lock` still
named the 3.11 it had been compiled with. All five workflows now use the
shipped version, and `scripts/check_python_version.py` fails CI if the
Dockerfile, the workflows and the lockfile ever disagree again. The Dockerfile
is the declared source of truth, since it is what ships.

**Lockfile.** `requirements.lock` was hash-pinned and carefully generated —
and installed by nobody: all six entry points (Dockerfile, `ci`, `sbom`,
`release`, `verapdf`, `build-desktop`) installed from `requirements.txt`.
Dependabot has no concept of it, so it drifted unnoticed: 32 commits to
`requirements.txt` in six months against 4 to the lockfile, one of those only
line endings. It ended up missing four packages outright — `mammoth`,
`pikepdf`, `Babel`, `prometheus-client` — and behind on five more, including
`uvicorn` (0.46.0 against a `>=0.49.0` constraint). A lockfile with no
consumer and no gate is decoration that reads as a guarantee.

It is now real: the Dockerfile installs with `pip install --require-hashes -r
requirements.lock`, `pip-audit` audits the lockfile instead of the manifest
(the lockfile being what reaches production), a `lockfile-drift` CI job
recompiles and diffs against the committed file — uploading the correct one as
an artifact when it fails — and a `deps-lock` workflow regenerates and commits
it on demand. Dependabot's own config now documents that its pip PRs turn that
gate red until the lockfile follows.

The lockfile is now compiled by **uv** rather than pip-compile, pinned to an
exact version like ruff. pip-compile can only resolve for the interpreter it
runs on, which is the mechanical reason this drifted in the first place: the
committed lockfile carried 3.11 because that was somebody's local Python, and
nobody could regenerate it for the image without installing 3.14 first. `uv pip
compile --python-version 3.14` resolves *for* the shipped interpreter from any
machine, so keeping the lockfile current no longer depends on matching the
image locally. The regenerated lockfile covers 76 packages with 2003 hashes,
and all 30 direct dependencies now satisfy their constraints — previously five
did not. `.gitattributes` pins the lockfile to LF so a CRLF checkout cannot
make the drift gate compare Windows-generated against Linux-generated output.

Documentation corrected alongside: `patch-policy.md` claimed direct
dependencies were "pinned to a specific minor version" (they carry `>=`
constraints) and treated the lockfile as optional;
`vendor-security-questionnaire.md` repeated that pinning claim and named the
wrong `pip-audit` target; the regeneration recipe in
`third-party-licenses.md` now matches what actually ships. `self-hosting.md`
gains a "Reproducible builds" section — the gap the internal promise audit
tracked as M1.

### Fixed — trusted-proxy guidance pointed at the wrong knob

`security-overview.md` § Operational Hardening told self-hosters that the rate
limiter "trusts the `X-Forwarded-For` header" and to close the gap with nginx's
`set_real_ip_from` or Caddy's `trusted_proxies`. Both halves are wrong for the
shipped default. `app/core/rate_limit.py` keys on `get_remote_address`, which
reads `request.client.host` only — never the header (that is slowapi's other
helper, `get_ipaddr`, which the app does not use). uvicorn rewrites
`request.client` from `X-Forwarded-For` solely when the peer is covered by
`FORWARDED_ALLOW_IPS`, default `127.0.0.1`; under Docker the proxy arrives from
the bridge network, so it never matches. Proxy-side directives cannot move
uvicorn's trust boundary.

The live consequence is the inverse of the documented one: instead of clients
rotating IPs to escape the limit, every anonymous request keys to the same
bridge-gateway address, so all visitors share a single 60/min bucket. Item 3 now
says that, names `FORWARDED_ALLOW_IPS` as the actual lever, warns against `*`,
and keeps the proxy-side directives as the complement they are. The PT-006 entry
that pointed at the old instruction is corrected alongside.

`security-pentest-report.md` gains a post-audit correction note on finding 4,
which attributes header-reading to the wrong slowapi helper; the original
finding text is left intact, and the PT-006 residual row now names the real
knob.

Docs only; no code change.

### Fixed — HSTS docs now describe what is actually served

The security docs stated that `security_headers` emits
`Strict-Transport-Security: max-age=31536000; includeSubDomains` on every HTTPS
response. It did not. The middleware gates on `request.url.scheme`, which uvicorn
derives from `X-Forwarded-Proto` — and uvicorn honours that header from
`127.0.0.1` only unless `--forwarded-allow-ips` widens it. Under Docker the proxy
reaches the container across the bridge network, so the header was discarded and
no HSTS ever shipped. The claim was externally falsifiable with a single `curl`,
which made it a liability in `vendor-security-questionnaire.md` in particular.

filemorph.io now serves `max-age=15552000` (6 months, no `includeSubDomains`, no
preload) from the Cloudflare edge; `security-overview.md`, `dpa-tom-annex.md` and
the vendor questionnaire say so, and separate the managed service from the
self-hosted case. `self-hosting.md` gains an "HSTS behind Docker" section
documenting both remedies — a proxy-set header (Caddy and nginx snippets), or
naming the proxy in `FORWARDED_ALLOW_IPS` via `.env` — with an external
verification command.

The second remedy is documented as a named address or CIDR, never `*`. With `*`
uvicorn takes the leftmost `X-Forwarded-For` entry, and both documented proxies
append to the client-supplied header, so any visitor could forge the address
uvicorn records — through the proxy, with port 8000 closed. That address is the
rate-limit key (`app/core/rate_limit.py`), the anonymous quota identity, and the
audit log's `actor_ip`. The section also flags that the shipped compose file
publishes port 8000 on every host interface. `.env.example` documents the knob,
commented out — an empty value would trust no peer at all and break the
bare-metal setup that works today.

No behaviour change: the only non-Markdown edit is a docstring in
`tests/test_security_headers.py` that carried the same corrected-away claim. The
middleware still emits nothing under Docker, so self-hosters must apply one of
the two documented remedies.

### Added — /compress landing page (IA rework PR 4)

Final slice of the navigation/IA rework (`docs-internal/ia-navigation-konzept.md`).
Compress-to-a-target-size — the product's flagship differentiator — gets its own
URL: `/compress` embeds the same Convert/Compress tool as the homepage, pre-set
to Compress mode via a `data-preset-mode` attribute (`app.js` calls the existing
`setMode('compress')` on init when it's present; CSP-safe, no inline JS), plus an
honest-limits section, a 3-step "how it works", a "when to use it" paragraph, an
FAQ (one entry states plainly that exact target-size compression only works for
JPEG/WebP — video and PNG/TIFF compress by quality instead), a "PDFs?" pointer to
`/pdf/compress`, and a related-tools row. Title/meta deliberately never say
"pdf" (cannibalization guard — the PDF slice of this query space stays on
`/pdf/compress`). `/tools` gets a second card, "Compress to a target size",
next to Convert & Compress; the Convert card's own description no longer
claims video hits an exact target (it never could — `compress_video()` only
takes a quality/CRF re-encode) and now only names batch conversion, its one
remaining URL-less mode. `/formats`' "Compress to a target size" CTA now
points at `/compress` instead of `/`, and its intro paragraph gets the same
video-target-size correction. Sitemap (`priority=0.7`, matching `/pdf/compress`)
and `llms.txt` list the new page in the same commit.

### Changed — homepage "More tools" section, heading hierarchy fix (IA rework PR 3)

Third slice of the navigation/IA rework (`docs-internal/ia-navigation-konzept.md`).
The homepage's two separate tool teasers — the gated Redact card and the ungated
PDF-tools card — are merged into one "More tools" / "Weitere Tools" section: PDF
Split/Extract/Compress, Redact PII (still gated on `ai_operations_enabled`), and a
closing "All tools →" link to `/tools` (reusing the same label the footer's Tools
group already uses). The Plans and For-Developers blocks now use a real `<h2>`
instead of a decorative eyebrow `<p>` (WCAG 1.3.1 heading hierarchy) — same
classes, no copy change.

### Added — /tools operations hub, /formats becomes format-first (IA rework PR 2)

Second slice of the navigation/IA rework (`docs-internal/ia-navigation-konzept.md`).
A new `/tools` page is the operations-first counterpart to the format-first
`/formats` matrix: cards for Convert & Compress (the only place the
compress-to-target-size and multi-file-batch modes are described, since
neither has its own URL), the three PDF structural tools, and — gated on
`ai_operations_enabled` — Redact PII, labelled "(Pro)" as plain text, no
badge styling. The navbar's "Convert" item is now "Tools" (desktop + mobile)
and links here; the footer's Tools group gets a new first link, "All tools
→". `/formats` drops its 3-sub-block "PDF tools" section in favour of one
cross-link to `/tools` (and vice versa); its conversion-matrix chips are now
clickable `<a>` links to `/convert/<src>-to-<tgt>` for the 12 curated pairs,
while uncurated chips stay plain `<span>`s (unchanged honest signal). Each
`/pdf/{split,extract,compress}` page gets a new "Related tools" block after
the FAQ, linking its two sibling PDF tools, `/formats`, and 1-2 topically
relevant curated convert pairs (e.g. compress links `docx-to-pdf` and
`jpg-to-pdf`) — fixing the previous dead end. `/tools` is listed in the
sitemap (priority 0.8) and `llms.txt`, which also gains a "Conversions"
section listing every curated pair URL — both generated from the existing
registries, not hardcoded.

### Changed — footer regrouped into Tools/Product/Legal, redact nav-slot removed

First slice of the navigation/IA rework (`docs-internal/ia-navigation-konzept.md`).
The footer's flat link row is now three named, server-rendered groups — Tools
(Split/Extract/Compress PDF, Redact PII*, Formats), Product (Self-Hosted,
Pricing*, Enterprise*, API Docs, GitHub), Legal (Privacy, Terms, Impressum,
Contact) — same label styling as the unchanged "Popular conversions" grid;
the copyright line moved onto its own line. The client-side-hydrated
`#nav-ai-slot` / `#nav-ai-slot-mobile` (`auth.js`'s `_renderAiNavLink`) is
gone: Redact PII is no longer a navbar item, discoverable via the footer
(flag-gated) and homepage teaser only, so every nav/footer link is now
server-rendered in the raw HTML (CSP hardening — visibility never depends on
a client-side fetch). Mobile nav order now matches desktop (language switcher
moved to just before the auth block). Quota-error states (`input_too_large` /
`output_cap_exceeded` / `target_size_exceeds_cap`) on the PDF tools and the
main Convert/Compress tool now show a "See plans and limits →" link next to
the existing honest error text, only when `pricing_enabled` (self-host builds
render no element). PDF-compress's "nothing to recompress" outcome now labels
the download button "Download unchanged file" instead of the default
"Download PDF", so it never implies a compression that didn't happen.

### Added — Web UI for the PDF structural-operation tools

Three focused, bilingual (DE/EN) landing pages for the PDF page-extract /
split / compress-to-target API added above — `/pdf/split`, `/pdf/extract`,
`/pdf/compress` — each with its own SEO content (distinct search intent per
tool), an embedded working tool, and an honest-limits / how-it-works / FAQ
section. Ungated (free, no account, like the main Convert/Compress tool).
**Honest compress UX:** the result reads `X-FileMorph-Converged` /
`X-FileMorph-Recompressible-Images` and shows a plain amber notice — with the
achieved size — when a PDF has nothing to recompress or the target wasn't
fully reached, rather than claiming a compression that didn't happen; the
download is offered regardless. Discoverable via the sitemap, `llms.txt`, the
footer, the homepage, and a new "PDF tools" section on `/formats`.

### Changed — identity conversion pairs hidden from user-facing listings

`GET /api/v1/formats` and the `/formats` page / convert-tool dropdown no
longer list a same-format pair (e.g. "PDF → PDF") as a *target* — offering it
was a silent no-op re-save. A new `get_public_conversions()` filters the live
registry for user-facing listings only; `/api/v1/convert` and the raw
registry are unaffected (`pdf → pdf` still works via the API and backs the
page-extract/split/compress routes above). The Convert card shows a hint
linking to the dedicated PDF tools when the selected file is a PDF.
`X-FileMorph-Converged` and `X-FileMorph-Recompressible-Images` were added to
CORS `expose_headers` (same-origin today, but future-proofs the S1.5
cross-origin upload split) alongside the Web UI change above.

### Added — PDF structural operations (page extract / split / compress-to-target)

Three pure-Python *morph* operations on existing PDFs, each a dedicated
same-origin route reusing the shared hardening pipeline (magic-byte guard, tier
caps, output cap, `asyncio.to_thread` offload, UUID temp dir, generic errors):

- **`POST /api/v1/pdf/extract`** (`pages=1-3,5`, 1-based) — write a new PDF with
  only the selected pages; text/fonts/vector copied intact. Malformed / reversed
  / out-of-range / non-numeric selections are a clean `400` (no pypdf internals
  leaked); a selection is capped at 10 000 pages.
- **`POST /api/v1/pdf/split`** — one single-page PDF per page, bundled as a ZIP
  (`page_001.pdf`, … zero-padded). Capped at **10 000 pages** (a larger document
  is a `400` before any work, so a crafted huge-page PDF can't exhaust memory).
- **`POST /api/v1/pdf/compress`** (`target_kb`) — shrink toward a byte budget by
  recompressing embedded raster images (binary search on a global JPEG quality);
  page count and every glyph preserved. **Honest limits:** only image-heavy PDFs
  shrink — a text/vector-only PDF (or one whose images are all masks / palette /
  alpha) comes back valid and unchanged, reported `X-FileMorph-Converged: false`
  / `X-FileMorph-Recompressible-Images: 0` rather than a fake compression claim.
  Response headers `X-FileMorph-Achieved-Bytes`, `X-FileMorph-Converged`,
  `X-FileMorph-Recompressible-Images`. A working-set ceiling caps the total
  decoded pixel area / image count and bails to the unchanged-PDF path instead
  of decoding a crafted image-bomb PDF (DoS guard mirroring the single-image
  decompression-bomb hardening).

### Added — AVIF image encode + decode

AVIF (AV1-based image format) is now a first-class image format for both
conversion and compression, via the new `pillow-avif-plugin` dependency
(libavif bundled in the wheel — no system package). Every `*→avif` and
`avif→*` pair is registered through the existing generic image converter, and
AVIF joins the quality- and **target-size**-compression sets (binary search on
quality, like JPEG/WebP). EXIF/GPS metadata is stripped on every AVIF write,
matching the existing privacy posture. **Honest note:** AVIF/AV1 encode is more
CPU-intensive than JPEG/WebP — a single encode is slower, and target-size
compression runs several encode passes; decoding from AVIF is cheap.

### Security — accepted advisory PYSEC-2026-1325 (`ecdsa`, no fix available)

`pip-audit` in CI now ignores PYSEC-2026-1325 (= CVE-2024-23342, the Minerva
timing side-channel in the `ecdsa` package, pulled in transitively by
`python-jose`). No fixed release exists and upstream considers side-channel
attacks out of scope. FileMorph is not affected in practice: all JWTs are
signed and verified with HS256 only (`app/core/tokens.py`), so the vulnerable
ECDSA signing/keygen/ECDH paths are never executed. The exception is documented
next to the ignore flag in `ci.yml` and is re-evaluated at each release;
migrating off `python-jose` would remove the dependency entirely.

### Added — PII redaction (Enterprise Edition, commercial add-on)

Deterministic, local-CPU PII redaction for UTF-8 text, DOCX and XLSX — detects
IBAN (mod-97), email, phone, IPv4 and payment-card (Luhn) by regex + checksum,
no external model call. A mandatory **fail-closed** pass re-scans the *serialized
output package* (all XML parts — body, metadata, comments, sheet names,
attributes), so a half-redacted file is never returned. Lives under `app/ee/`
(commercial-licensed); inert unless `AI_OPERATIONS_ENABLED` is set.
**Honest limits:** free-text names and postal addresses are not detected yet (no
NER), and PDF is unsupported (returns 415 — safe PDF redaction must delete the
text layer, a separate checkpoint; we don't ship a cover-only fake).

### Added — Redaction API + `/redact` tool page

`POST /api/v1/ai/redact/{detect,apply}`: two-phase — `detect` returns a free
findings preview (open to anonymous/free users); `apply` produces the redacted
file (paid-tier-gated, credit-metered, atomic charge). CPU work runs off the
event loop. New `/redact` page (gated on `AI_OPERATIONS_ENABLED`, 404 when off)
with a free scan → review → download flow, an honest scope notice, footer link,
homepage/pricing/enterprise surfaces, and an eligible-only nav link. Responses
are credit-denominated only — never a model id, token count, or euro cost.

### Changed — Footer "Popular conversions" uses explicit pair labels

Replaced the target-grouped footer layout (a "→ PDF" heading with bare source
names beneath — hard to parse and sparse) with explicit, directly-readable
`JPG → PDF` labels in a balanced responsive multi-column grid. Each conversion
is self-explanatory and one click away; the columns fill the width evenly.
`convert_pairs.FOOTER_LINKS` (flat) replaces `FOOTER_LINK_GROUPS`.

### Changed — Hide the Target Format dropdown on convert-pair pages

On `/convert/<src>-to-<tgt>` the target is fixed by the URL, so the "Target
Format" label + dropdown are no longer shown — the page itself is the choice.
The `<select id="target-format">` stays in the DOM (hidden) because `app.js`
reads it for submit, the download-name fallback, and the bandwidth-amplification
warning (which stays visible). Confirmed **frontend-only** by the
backend-architect: the conversion reuses the format-agnostic
`POST /api/v1/convert` (`target_format` from the form), so no backend or
API-contract change — a per-pair endpoint would just duplicate the
security/quota pipeline.

### Fixed — Convert-tool German strings (i18n partial-scan regression)

When the convert tool card was extracted into a Jinja partial under
`app/templates/_components/`, babel's extractor — which prunes underscore-
prefixed directories — stopped scanning it, so ~26 tool strings (drag-&-drop,
"Supported: …", Target Format, Quality, Download Result, …) silently fell back
to **English on `/de/`**. Moved the content partial to
`app/templates/partials/convert_tool.html` (scanned normally), documented the
underscore-dir limitation in `babel.cfg`, recovered the German translations,
and added a regression test asserting the partial renders translated on `/de/`.

### Changed — Dedicated convert-pair pages + structured footer

- **`/convert/<src>-to-<tgt>` pages are now a focused tool**, not the generic
  app: the upload shows only the pair's source format, `#file-input` gets an
  `accept` scoped to it, and the Convert/Compress toggle is hidden (a
  conversion pair is convert-only). The target stays pre-selected.
- **Footer "Popular conversions"** is grouped by target format ("→ PDF",
  "→ JPG", …) in a responsive grid (stacked columns) instead of a ragged inline
  row — more scannable, same internal-link coverage.

### Added — Footer links to the convert-pair pages

The global footer (`base.html`, every page) now has a "Popular conversions"
row linking all curated `/convert/<src>-to-<tgt>` pages — spreading internal
link equity to them on every page and aiding discovery (the standard SEO
footer pattern). Language-neutral arrow labels ("JPG → PDF"), locale-aware
hrefs; `footer_convert_links` is injected into every render context via
`app/core/i18n.py::localized_context` (lazy import to avoid the
i18n↔convert_pairs cycle). Guards in `tests/test_convert_pair_pages.py`.

### Added — Convert-pair landing pages (`/convert/<src>-to-<tgt>`)

Penalty-safe programmatic SEO pages for the highest-volume conversions
(`/convert/jpg-to-pdf`, `/convert/heic-to-jpg`, …). Each page **embeds the
real, working converter pre-set to that pair** — the tool card was extracted
into a shared `app/templates/_components/convert_tool.html` partial, and
`app.js` reads `data-preset-target` to pre-select the format (not disabled, so
the user can still change it). Alongside the tool, each page carries **unique,
localized (DE/EN) content**: when-to-use, technical/size-amplification notes, a
visible question-heading FAQ (GEO) and related-pair links. 12 curated pairs to
start. A page exists **only** when hand-written content lives in
`app/core/convert_pairs.py` *and* the conversion is registered — anything else
404s, so there are no thin auto-generated pages (Google 2026 "scaled content
abuse" safety; measure in Search Console, then scale). The sitemap
auto-populates the pairs (de/en/x-default + hreflang). New `convert_pair.html`
+ route in `pages.py`; +68 guards in `tests/test_convert_pair_pages.py`.

### Added — image / HTML / email → PDF converters

Three new "to-PDF" conversions, all **zero new dependencies** (Pillow + the
in-tree WeasyPrint engine). **`image→pdf`** (every supported image format →
single-page PDF; alpha flattened onto white, EXIF stripped) — useful for turning
scans/photos into uniform documents. **`html→pdf`** and **`eml→pdf`** (email:
common headers + body, HTML part preferred) render via WeasyPrint with the
mandatory `url_fetcher=_deny_url_fetcher` SSRF guard, so remote CSS/images and
`file://` are never fetched. New converters live in `app/converters/image.py`
and `document.py` (auto-registered, so they appear on `/formats` +
`/api/v1/formats`); guards in `tests/test_to_pdf_converters.py` (valid PDF
output, SSRF-blocked, magic-byte still enforced). `.msg` (Outlook) deferred —
it would need a new dependency.

### Fixed — Media conversion correctness: per-container codec matrix, direct ffmpeg audio, hard timeouts

The video converter forced `libx264`/`aac` into every container — but the
WebM muxer only accepts VP9/Opus and ffmpeg has no muxers named `mkv`/`wmv`
(the real names are `matroska`/`asf`), so **18 of the 42 advertised video
pairs failed at runtime** with a generic 500. Video output now uses a
per-container codec matrix (`app/converters/_ffmpeg.py`): WebM → VP9/Opus,
AVI → MPEG-4/MP3 (legacy-player compatibility), WMV → WMV2/WMA, everything
else H.264/AAC with `yuv420p` for player compatibility (odd-dimension
sources are rounded down one pixel instead of failing). The `quality`
parameter (previously accepted and ignored for media) now drives each
encoder's native rate control (CRF/qscale/VBR/bitrate).

Audio conversion drops pydub (unmaintained since 2021): it decoded the
whole file to PCM in RAM (a 100 MB MP3 is >1 GB decoded — an OOM vector
under the 500 MB Business input cap) and passed the bare extension as the
ffmpeg output format, **breaking m4a/aac/wma targets** (no such muxers;
correct: `ipod`/`adts`/`asf`). Audio now invokes ffmpeg directly with
constant memory and per-codec quality mapping; embedded cover-art streams
are dropped (consistent with the NEU-C.2 strip-metadata default).

`/compress` for video previously remuxed **everything into MP4 while
keeping the original extension** (a compressed `.webm` was an MP4 file
mislabelled as WebM); it now preserves the container and picks codecs from
the same matrix. Every ffmpeg invocation now runs under a hard timeout
(`MEDIA_SUBPROCESS_TIMEOUT_SECONDS`, default 600 s) like the LibreOffice
and ghostscript subprocesses already did — no more unbounded worker-thread
pinning. New functional smoke matrix (`tests/test_media_smoke.py`)
generates 1-second clips via ffmpeg `lavfi` in CI and verifies container +
codecs of every video/audio target with ffprobe (skips cleanly where
ffmpeg is absent, e.g. local Windows dev).

### Fixed — Social-preview (og-image) logo

The `app/static/og-image.png` social card showed a different, off-brand mark
(an empty box with two arrows) instead of the real FileMorph logo. Regenerated
it to use the **same document-tray + download-arrow mark as `favicon.svg`/the
navbar** (brand indigo `#6366f1`), wordmark and chips unchanged. Added a
Pillow-only, reproducible generator `scripts/generate_og_image.py` (the asset
previously had none, which is how it drifted) — re-run it after any logo or
wording change. Still 1200×630, no SaaS host string baked in.

### Added — SEO/GEO visibility foundation (Phase 1)

Sharpens organic-search and AI-answer-engine discoverability without touching
the conversion engine. **On-page:** keyword-front, SERP-length-safe titles
(≤60) and a per-page `meta_description` block in `base.html` (the homepage DE
title now carries the exact-match phrase "Dateien … konvertieren"); a homepage
FAQ section (question-style `<h3>` headings) and an honest "FileMorph vs.
typical cloud converter" comparison table — visible content built for AI
extractability (GEO). **Structured data:** an `Organization` entity
(`sameAs` → GitHub) and an honest `featureList` added to the homepage JSON-LD
(still one CSP-hashed, deployment-agnostic block). **GEO:** a new `/llms.txt`
entry point (llmstxt.org convention) and explicit AI-crawler allowances in
`robots.txt` (GPTBot, ClaudeBot, PerplexityBot, Google-Extended, …). **New
`/formats` hub** that renders the live `@register` converter registry grouped
by category — a unique-content, ungated, sitemap-listed discovery page (and the
anchor for future per-pair pages). Fully localised (DE 100 %, drift-check
green) and deployment-agnostic. Adds 14 regression guards to
`tests/test_seo_foundation.py`; also clears a stale `Compression`→`Imprint`
fuzzy entry in the EN catalogue.

### Added — Account-deletion paid-path (tax-retention, c.2)

Extends the free-path self-service deletion (`DELETE /api/v1/auth/account`)
with the **paid-account path** required by German commercial law. Accounts
ever linked to Stripe now get a **restricted delete** instead of a hard
delete: only `email`, `stripe_customer_id`, `tier`, `created_at` are
retained, everything else is nulled, `password_hash` becomes a `DELETED:`
sentinel, and `deleted_at` is set (HGB §257 / AO §147 10-year retention
under DSGVO Art. 17(3)(b)). New `app/core/account_deletion.py`
(`deletion_mode_for` + `perform_account_deletion`), migration
`010_account_deletion_paid_path` (`users.deleted_at` + partial unique index
`ix_users_email_active`), Stripe cancel-first ordering, a dashboard
"Danger Zone" + `/account-deleted` page. Lookup queries filter
`deleted_at IS NULL`. Also fixes `scripts/scope_review.py` to decode the
staged diff as UTF-8 (was crashing the advisory hook on non-ASCII diffs).

### Added — Localised transactional email (i18n-3)

All transactional emails (verification, password-reset, account-deletion,
dunning) now render in the recipient's `preferred_lang` (`de`/`en`) via
`email.render_email(stem, locale=…)` and `{% trans %}` templates. A new
`User.preferred_lang` column (migration `009_preferred_lang`, NULL →
`LANG_DEFAULT`) is seeded from the request locale at registration and is
changeable via `PUT /api/v1/auth/account/language` plus a dashboard
language picker. The dunning mail — fired from a Stripe webhook with no
request context — reads the column. Web-UI locale stays URL-prefix-driven;
a sticky logged-in web-UI preference is a follow-up (PR-i18n-4).

---

## [1.1.0] — 2026-05-29

The Compliance-First strategic pivot (2026-05): FileMorph adds the
auditability + traceability surface that DACH Behörden, Krankenhäuser,
and Anwaltskanzleien expect. None of this changes the existing public
API behaviour for casual callers — every change is additive, defaulted
off where applicable, and optional at deploy time.

### Added — Homepage Self-Hosted promotion + nav anchor

The canonical product truth (open-source AGPLv3 engine, runs on your own
infrastructure — see `docs-internal/pricing-overhaul-konzept.md` §1) was
barely visible on the homepage: a single grey `mailto:` line at the
bottom. This sprint adds a real promotion surface so a visitor scanning
for "can I self-host this?" sees the answer on the highest-authority page.

- `app/templates/index.html` — new `id="self-hosted"` section directly
  after the tool card. Lists only **real** features (AGPLv3, Docker
  deploy, signed releases + CycloneDX SBOM, audit-log hash chain,
  PDF/A-2b, EU hosting) per the §7 honesty guardrail. Primary CTA →
  upstream `docs/self-hosting.md` on GitHub (always available, including
  on self-host). Secondary CTA → `/enterprise` Compliance Edition,
  gated by `pricing_enabled` so a self-host deployment doesn't link to
  its own 404. The pre-existing weak `enterprise@filemorph.io`
  `mailto:` line is removed — the section supersedes it, and gating the
  Compliance CTA prevents self-host deployments from advertising the
  upstream procurement contact as if it were their own.
- `app/templates/base.html` — ungated "Self-Hosted" nav entry (desktop
  + mobile) that points at the homepage `#self-hosted` anchor. Anchor
  navigation needs no JS (CSP-safe). The link works on every
  deployment because the section is always rendered.
- Internal link graph: the homepage now has a direct, gated link to
  `/enterprise`, strengthening the commercial page's inbound equity.
  Sitemap already covers `/enterprise` when `pricing_page_enabled`.

### Fixed — Homepage tier teaser now reads from the central pricing source

The pricing-overhaul (`feat(pricing)` 153f72d on this branch) made
`/pricing` deployment-agnostic via `app/core/pricing.py`, but missed the
homepage tier teaser in `index.html`, which kept hardcoding `Pro €7/mo`,
`Business €19`, `Free 50 MB`, `anon 20 MB`. `/pricing` therefore said
`€3`/`€9` while the homepage still said `€7`/`€19` — a fresh drift the
overhaul was meant to prevent.

- `app/api/routes/pages.py` — `index()` now passes `anon_plan`, `plans`,
  `saas_prices_configured`, and `price_currency` to the template,
  mirroring `pricing_page()`'s contract. Cheap (`pricing` helpers read
  from settings + `quotas.py`, no DB).
- `app/templates/index.html` — teaser pulls limits from `quotas.py` via
  `plans.<tier>.max_file_size_mb`/`.api_calls_display` and prices from
  `PRICE_*_DISPLAY` env via `plans.<tier>.price_display`. When a price
  isn't configured the `· €N/mo` suffix collapses — a self-host
  operator who enabled the pricing page without setting display prices
  no longer inherits filemorph.io's amounts.
- `tests/test_seo_foundation.py` — eleven new tests guard: section
  always rendered (both modes), Self-hosting guide link points at the
  GitHub repo (not `filemorph.io`), nav anchor present on both modes,
  Compliance CTA gated, teaser reads from configured price, no legacy
  `€7/mo`/`€19` strings ever reappear.

### Added — Prometheus metrics endpoint (`/api/v1/metrics`)

Request-path observability for self-hosters and the Compliance Edition.
Gated by `METRICS_ENABLED` (default `true`; the same flag the cockpit's
analytics card already references). When disabled, no instrumentation is
attached and the endpoint 404s — a single-tenant deployment that doesn't
run Prometheus pays nothing.

- `app/core/observability.py` — new. A small request-timing middleware
  (built on the raw `prometheus-client`, not the FastAPI instrumentator
  wrapper) records `http_requests_total{method,handler,status}` and the
  `http_request_duration_seconds{method,handler}` histogram, plus a
  domain counter `filemorph_conversions_total{operation,src,tgt,status}`.
  The middleware is attached last in `app/main.py` so it sits outermost
  and measures full request time.
- **Raw client, not the wrapper — a security choice.** The
  `prometheus-fastapi-instrumentator` wrapper pins `starlette<1.0.0`,
  which would hold the dependency below the `1.0.1` fix for
  PYSEC-2026-161 (Host-header URL-reconstruction / auth-bypass class).
  The raw `prometheus-client` has no such constraint, so the CVE scan
  stays clean and starlette floats to the patched release.
- **Cardinality is capped.** `src`/`tgt` and the request `handler` come
  from request data, so unknown formats collapse to `other` and an
  unmatched path (404) reports `handler="other"`; the label space is
  bounded by registered routes and formats, not by what a caller sends.
- `app/api/routes/convert.py` + `compress.py` — increment the domain
  counter at the same success/failure sites that already feed the
  `daily_metrics` table (single + batch), so the cockpit's DB counters
  and the scrape-friendly counter never diverge.
- The endpoint is **unauthenticated by design** (standard Prometheus
  pattern) and must be IP-restricted at the reverse proxy — see
  `docs/self-hosting.md` (Monitoring & metrics) and
  `docs/security-overview.md`.
- Tests: `tests/test_observability_metrics.py` (exposition format,
  counter increment + visibility, cardinality cap, disabled-path no-op).
- Grafana dashboards / alert rules are a follow-up (private ops repo);
  the OSS app ships only the instrumentation + endpoint.

### Fixed — CSP: inline i18n bootstrap moved to an external file

The `window.FM_I18N = JSON.parse(...)` bootstrap in `base.html` was an
inline `<script>` with no `src` and no pinned hash, so the strict CSP
(`script-src 'self' 'sha256-<jsonld>'`) blocked it on every page. The
block was silent server-side (the page still renders) but visible in the
browser console, and because the blocked script never runs, its `catch`
never fired — `window.FM_I18N` stayed `undefined` and every JS string
fell back to its English literal. Most visible on `/de/dashboard`, where
German copy silently rendered in English.

- `app/static/js/i18n-bootstrap.js` — new. Parses the `#fm-i18n-strings`
  data block into `window.FM_I18N`, loaded via `<script src>` before the
  consumer scripts (nav/auth/app). No inline executable script remains.
- `app/main.py::_build_csp_header` — added `base-uri 'self'` and
  `frame-ancestors 'none'` while in the file.
- `tests/test_csp_no_unpinned_inline_scripts.py` — new regression guard:
  every inline executable `<script>` on `/`, `/dashboard`,
  `/{de,en}/dashboard`, `/cockpit`, `/de/cockpit` must have its SHA-256
  in that page's own CSP, or the build fails.
- `docs/security-overview.md` — CSP section corrected (it still described
  a Tailwind inline-config block that no longer exists).

### Polished — Mobile-UX touch-target sweep (P1-5)

Structural audit of every template at the 375 px viewport flagged a
handful of touch targets below the W3C/Apple-HIG 44 px minimum and
one grid that didn't stack on narrow screens. Concrete fixes:

- `app/templates/index.html` — Tier-teaser grid `grid-cols-3` →
  `grid-cols-1 sm:grid-cols-3`. On phones the three plan badges now
  stack instead of crushing into ~114 px wide cards.
- `app/templates/base.html` — Mobile drawer nav links bumped from
  `py-1` (~28 px) to `py-2.5` (~40 px). Seven links + auth-mobile
  pair touched.
- `app/templates/cockpit.html` — Six chart range-buttons + four
  filter controls (search input + 3 selects) + two pagination
  buttons lifted from `py-1` / `py-1.5 text-xs` to `py-2 text-sm`.
  Admin-only UI but the operator runs the cockpit from a phone
  during incident response.
- `app/templates/dashboard.html` — API-key Copy button consistency:
  `py-2 text-xs` → `py-2.5 text-sm`.

Total: 4 files, 14 line-level edits. No new components, no JS
changes, no layout rework. The audit's "verify on a real device"
list (native iOS picker behaviour, keyboard-pop coverage of submit
buttons, modal scroll-lock on iOS Safari bounce-scroll) remains
open as a `device-only` validation pass for a manual browser
session.

### Added — Per-file batch result summary (P2-1)

- `/api/v1/convert/batch` and `/api/v1/compress/batch` now emit four
  structured response headers alongside the ZIP body:
  `X-FileMorph-Batch-Total`, `X-FileMorph-Batch-Succeeded`,
  `X-FileMorph-Batch-Failed`, and (only when at least one file
  errored) `X-FileMorph-Batch-Failures` — a semicolon-joined list
  of URL-encoded `<name>|<reason>` pairs, capped at 4 KB to stay
  under typical proxy limits with a `...` sentinel signalling
  truncation. The `manifest.json` inside the ZIP remains the full
  source of truth for callers who want the complete detail.
- Web UI reads the headers after a successful batch response and
  renders a per-file summary block above the green download button —
  emerald tone when 0 failures, amber tone otherwise, with each
  failed filename rendered as `<code>` next to its server-reported
  reason. The user no longer has to unzip the ZIP just to see which
  file failed and why.
- CORS `expose_headers` extended in `app/main.py` so cross-origin
  clients can read the new headers.
- Tests: existing `test_batch_partial_failure_continues` extended
  to pin the headers on partial-failure; new
  `test_batch_all_success_omits_failures_header` pins the
  all-success contract (no `Failures` header when nothing failed).
- New i18n key `batchSummaryCounts` carries the
  `{succeeded} of {total} files succeeded ({failed} failed)`
  template; German translation applied. Locale catalogue compiled
  + drift-check passes.

### Hardened — Multi-stage Dockerfile builder / runtime split (P3-8)

- `Dockerfile` now has three stages: `builder` (compilers + dev
  headers), `base` (runtime libs only — published as
  `filemorph:latest`), and `office` (base + LibreOffice + OFL fonts
  — published as `filemorph:office`). The `builder` stage installs
  `build-essential`, `libheif-dev`, `libffi-dev`, `libssl-dev` —
  the four packages needed *only* at Python-wheel-install time for
  the rare cases where a manylinux prebuild isn't available — and
  pip-installs the requirements into a venv at `/opt/venv`. The
  `base` stage copies just `/opt/venv` from the builder and installs
  only runtime libs (`ffmpeg`, `ghostscript`, `libheif1`, Cairo /
  Pango, curl).
- Effect on the running container: no gcc / ld / make / dev-headers
  on disk; smaller attack surface for any post-exploit probe; image
  size drops by the weight of those four apt sets
  (build-essential alone is ~120 MB extracted on bookworm).
  Pre-built wheels behave identically — only the install path
  changes, not the runtime ABI.
- `docs/third-party-licenses.md` updated: the libheif row points at
  the runtime `libheif1` package rather than the build-time
  `libheif-dev` headers.
- Pre-flight disk check in `filemorph-ops/deploy.sh` (the
  `MIN_FREE_GB=2` gate, commit `a30615e` in the ops-repo) keeps the
  same threshold — the office image still adds ~280 MB on top of
  the slim base; the savings stack on the *base* side, not on the
  LibreOffice apt set.

### Hardened — Pillow decompression-bomb hard-reject (P3-4)

- `app/core/image_hardening.py` (new) promotes Pillow's
  `DecompressionBombWarning` to a synchronously raised
  `DecompressionBombError` at startup. The stock warn-but-continue
  behaviour between the configured `MAX_IMAGE_PIXELS` threshold and
  2× the threshold was a denial-of-service vector for a conversion
  service: a 200 kB PNG with an IHDR claiming 60 000 × 60 000 pixels
  (~3.6 GP) coasted past every input-size check and pinned the worker
  decoding ~14 GB of memory before the output-cap guard rejected the
  result.
- New env var `FILEMORPH_IMAGE_MAX_MEGAPIXELS` (default 89, range
  1–10 000) lets self-hosters with explicit large-image use cases
  (GIS, scans, microscopy) raise the threshold. Garbage / out-of-range
  values fall back to the default rather than refusing to boot.
- `/api/v1/convert` and `/api/v1/compress` catch the
  `DecompressionBombError` specifically and emit HTTP 400 with
  `X-FileMorph-Error-Code: decompression_bomb` so the UI can render
  a distinct "image too large to decode safely" message instead of
  the generic 500. CORS expose-headers already includes
  `X-FileMorph-Error-Code` since the Sprint B 413-disambiguation
  commit, so cross-origin callers see it too.
- 6 new regression tests in `tests/test_image_hardening.py` pin the
  hardening module (MAX_IMAGE_PIXELS resolution, warning-to-error
  filter, env-var override + garbage-value fallback) and the two
  route handlers (400 + structured header on bomb input, no
  false-positive on normal-sized images).
- `docs/security-overview.md` § "Decompression bombs" updated from
  "Pillow default is in effect" to the current hard-reject contract.

### Added — DOCX → PDF high-fidelity engine (Technology-First Sprint A)

- Two-engine routing for DOCX → PDF in `app/converters/document.py`. A
  per-document complexity detector opens the OPC ZIP and probes for the
  features `mammoth` silently drops — footnotes, endnotes, headers,
  footers, OLE embeddings, multi-section page layout, OMML equations,
  multi-level numbered lists. Complex docs route to LibreOffice
  (`soffice --headless --convert-to pdf`); simple docs stay on the
  fast pure-Python mammoth+WeasyPrint path.
- New env var `FILEMORPH_OFFICE_ENGINE` (`auto` default,
  `libreoffice`, `mammoth`). `auto` does the routing described above
  and falls back to mammoth when `soffice` is missing, with a
  structured `X-FileMorph-Warnings` response header so the client
  knows fidelity was reduced (`engine=mammoth_fallback,
  reason=soffice_unavailable, simplified=footnotes, …`).
  `libreoffice` forces the high-fidelity path and fails loud when
  `soffice` isn't on PATH — for deployments that explicitly never
  want the fallback. `mammoth` forces the pure-Python path even when
  LibreOffice is installed (A/B comparison, predictability).
- New `filemorph:office` image variant. `Dockerfile` is now
  multi-stage: the `base` stage is the slim image
  (`ghcr.io/mrchenglen/filemorph:latest`, unchanged footprint),
  the `office` stage adds LibreOffice + OFL Calibri/Arial/Times-metric
  fonts (`fonts-crosextra-carlito`, `fonts-liberation`,
  `fonts-dejavu-core`) on top. The office image is published as
  `:office`, `:{version}-office`, and `:{major}.{minor}-office`,
  cosign-signed identically to the slim variant.
- New `docker-compose.office.yml` overlay for self-hosters who want
  the office image without changing the default
  `docker compose up` behaviour:
  `docker compose -f docker-compose.yml -f docker-compose.office.yml up -d`.
- `docs/formats.md`, `docs/self-hosting.md`, and
  `docs/tech-stack-rationale.md` updated to document the routing,
  the two image variants, and the historical decision trail (the
  2026-05-08 `docx2pdf` failure plus the AGPL § 13 reasoning against
  Aspose.Words now both live in the Considered-and-Rejected section).
- 21 new regression tests in `tests/test_docx_complexity.py` pinning
  every detector branch + every engine-resolution outcome + the full
  fallback chain. The existing `tests/test_convert_document.py` suite
  is unchanged and still skips on Windows dev boxes that lack
  GTK/Pango (CI on Linux + the Dockerfile both run it).

### Added — Public contact form (German Impressum, DDG §5)

- `/contact` page with a contact form (de / en / x-default). Submissions
  are emailed to the operator with `Reply-To` set to the sender so a
  reply goes straight back; **the message is not persisted** — only a
  hashed-email audit event (`contact.message.received`) is recorded.
  Anti-spam: a hidden honeypot field + a `5/hour` per-IP rate limit; no
  external captcha (keeps the "no external resources" privacy promise).
  New `app/api/routes/contact.py`, `app/templates/contact.html`,
  `app/static/js/contact.js`, `app/templates/_components/textarea.html`.
- The Impressum now lists the contact form as a second, fast-direct
  contact channel alongside the email address (German DDG §5 + ECJ
  C-298/07) and cites the current statute (`§ 5 DDG`) instead of the
  repealed `§ 5 TMG`. The footer gained a "Contact" link.
- Privacy policy: new § 2f documents the contact-form data flow
  (Art. 6(1)(f) GDPR, not persisted); § 3 extended accordingly.
- New env var `CONTACT_FORM_RECIPIENT_EMAIL` (optional; falls back to
  `SMTP_REPLY_TO` → `SMTP_FROM_EMAIL`). `app.core.email.send_email()`
  gained an optional `reply_to` parameter. `/contact` is in the sitemap.

### Added — Trust foundation (NEU-A)

- `security.txt` (RFC 9116) under `/.well-known/security.txt` plus a
  human-readable `/security` page and `SECURITY.md`.
- Architecture overview, sub-processor list, STRIDE threat model,
  patch policy, incident-response playbook, AGPLv3 explainer for
  German Behörden — all under `docs/`.
- `docs/support-sla.md` — the security-fix timeline (applies to every
  deployment, free or paid) and the Compliance-Edition support
  framework (set per agreement; no standing SLA during the
  design-partner phase), kept explicitly distinct.
- `docs/dpa-tom-annex.md` — "Annex II — Technical and Organisational
  Measures" template for the Article 28 DPA: structured along the
  Article 32 GDPR categories, with the application-level measures filled
  in (each with a code anchor) and the deployment-level measures as
  `[operator: …]` placeholders. Referenced from `docs/dpa-template.md` §7
  and its finalisation checklist.
- `docs/records-of-processing-template.md` — an Article 30 GDPR
  "Verzeichnis von Verarbeitungstätigkeiten" (Records of Processing
  Activities) template: an identification block, six controller
  activities (A1–A6) and one processor activity (B1), each with the
  Art. 30 fields (purpose, data subjects, data categories, recipients,
  transfers, retention, TOM reference), `[operator: …]` placeholders,
  and a prune-down note for Community-Edition deployments.
  `docs/dpa-template.md` §5 now distinguishes the audit log (a record of
  processing *operations*) from this register.
- `docs/onboarding.md` — defines the Compliance-Edition onboarding scope
  ("dedicated onboarding" at the Enterprise tier, lighter at the others):
  per-tier inclusion table, the contract-signed-to-go-live sequence,
  timeframe, and what is out of scope. Referenced from
  `COMMERCIAL-LICENSE.md`.
- `docs/commercial-license-agreement-template.md` — a signature-ready
  Commercial License Agreement skeleton (licence grant, term / renewal,
  fees, warranties, liability cap, third-party-IP indemnity,
  confidentiality, German law / Hamburg jurisdiction) with Schedules
  A–D wiring in the tier and fees, the Support SLA, the DPA + TOM annex,
  and the onboarding scope. Published for procurement review; flagged
  "not legal advice — have counsel review and tailor it before signing."
- `docs/vendor-security-questionnaire.md` — standing answers to the
  recurring questions in vendor security questionnaires (VSA, SIG / SIG
  Lite, CAIQ, BSI Grundschutz-style reviews, KRITIS / B3S supplier
  checklists, ad-hoc DPO worksheets). 16 sections — vendor ID, product
  overview, hosting / data residency, GDPR Art. 28 readiness, encryption,
  authN/authZ, application security (OWASP Top 10 walk), audit logging,
  vulnerability management, incident response, BCP/DR, source / supply
  chain / SBOM, certifications, support tiers, exit / portability,
  personnel, public artefacts index — each section cites the canonical
  source (DPA template, TOM annex, RoPA, support framework, pentest
  report, threat model). Lets a prospect's reviewer clear an internal
  threshold before any sales contact, and lets the operator hand a
  single PDF in response to a questionnaire instead of re-deriving the
  answers each time.
- `docs/third-party-licenses.md` — OSS-license posture for the
  dual-license model: the runtime dependency tree is permissive or
  MPL-2.0 throughout; the only GPL pieces are in the native layer
  (`x265` bundled-but-never-invoked in the `pillow-heif` wheel; Debian's
  GPL FFmpeg, driven as a separate program), neither affecting
  FileMorph's own licensing; GPL-free builds are offered per Compliance
  agreement; everything verifiable against the release CycloneDX SBOM.
  The `License Map` in `docs/tech-stack-rationale.md` was refreshed to
  match (pikepdf MPL-2.0, mammoth, Babel; corrected `pillow-heif` /
  FFmpeg rows).
- `docs/security-pentest-report.md` gained a status banner and a
  per-finding (PT-001 … PT-013) resolution table marking it as a
  historical April-2026 self-assessment (not an external pen test)
  superseded by `docs/security-overview.md`.
- CycloneDX SBOM generation in CI (`.github/workflows/sbom.yml`),
  attached to every GitHub release.
- `/enterprise` Compliance-Edition landing page.
- `COMMERCIAL-LICENSE.md` rewritten with the Compliance Edition
  tier structure (Starter / Standard / Enterprise / KRITIS).

### Added — Compliance code (NEU-B)

- **Tamper-evident audit log** with SHA-256 hash chain
  (`app/core/audit.py`, migration 005, Postgres append-only trigger).
  ISO 27001 A.12.4.1 / BORA §50 / BeurkG §39a compatible. `verify_chain`
  helper detects retroactive edits from a SQL dump alone.
- `X-Output-SHA256` response header on `/convert` + `/compress`,
  computed via chunk-streamed SHA-256 (NEU-B.2).
- `RETENTION_HOURS` configurable retention window, periodic
  background sweep of stale temp dirs.
- `auth.{register,login,password_reset,email_verification,account_deletion}.*`
  events feed the audit chain with hashed-email actor identifiers (no
  raw email storage).
- `cosign` keyless OIDC signing of every container image push
  (`.github/workflows/docker.yml`) plus GPG-signed git tags via
  `.github/workflows/release.yml` and a maintainer key list at
  `docs/release-signing.md` — the maintainer Ed25519 signing key
  (`security@filemorph.io`) is now registered there, so `release.yml`
  can publish signed releases; the doc also gained a "First-time setup"
  walkthrough for generating / rotating the key.

### Added — Use-case openers (NEU-C)

- **PDF/A-2b conversion target** at `/api/v1/convert?target_format=pdfa`.
  Two-path orchestration: ghostscript re-render path
  (`app/converters/_ghostscript.py`) embeds fonts and applies
  `-dPDFA=2`; pikepdf markup pass writes XMP `pdfaid:part=2` /
  `conformance=B`, GTS_PDFA1 OutputIntent with embedded sRGB ICC, and
  strips PDF/A-forbidden surfaces. Falls back to markup-only when gs
  is not on PATH.
- **veraPDF CI gate** (`.github/workflows/verapdf.yml`) runs the
  official veraPDF Docker image against a converter-produced fixture
  on every PR to main; fails the workflow on any conformance error.
- **EXIF/XMP/IPTC stripped by default** on every image conversion +
  compression (`app/converters/_metadata.py`). ICC profile preserved.
- **`X-Data-Classification` header** middleware
  (`app/core/data_classification.py`): BSI-style taxonomy
  (`public` / `internal` / `confidential` / `restricted`); echoed
  back on responses; propagated into every convert/compress
  audit-log payload.

### Added — Capacity (NEU-D)

- **Concurrency limiter** (`app/core/concurrency.py`): global
  semaphore + per-actor tier-bound semaphore with 0.5s acquire
  timeout. 503 (global capacity) vs. 429 (per-actor) with
  `Retry-After`.
- `/pricing` page surfaces the per-tier concurrency + rate-limit
  contract so callers can size their client pools.

### Added — Monthly API-call quota (PR-M)

- The per-tier monthly call limits (`api_calls_per_month` in
  `app/core/quotas.py` — 500 Free / 10 000 Pro / 100 000 Business)
  are now **enforced**, not just informational. `app/core/usage.py`
  records one `UsageRecord` row per successful `/convert`,
  `/convert/batch`, `/compress`, `/compress/batch` and counts the
  current calendar month (UTC) before each call. Over the limit →
  `429 Too Many Requests` + `Retry-After` pointing at the next month
  boundary. A batch counts as one call. Anonymous tier (per-IP
  rate-limit only) and Enterprise (unlimited) are exempt. Migration
  007 adds the `(user_id, timestamp)` index that keeps the gate
  query sub-millisecond.

### Changed — JWT `iss` / `aud` claims (PR-J)

- **Breaking for in-flight tokens.** Every JWT FileMorph mints
  (access, refresh, password-reset, email-verify) now carries the
  RFC 7519 `iss` and `aud` claims from `JWT_ISSUER` (default
  `filemorph`) / `JWT_AUDIENCE` (default `filemorph-api`), and every
  decode path validates them. A token minted before this change — or
  by a different FileMorph deployment, or by another service that
  shares a leaked secret — is rejected even with a valid HMAC.
  Existing sessions invalidate on the next request after upgrade
  (same blast radius as rotating `JWT_SECRET`). Multi-instance
  operators behind one identity provider should give each instance a
  distinct `JWT_AUDIENCE`.

### Added — Stripe dunning webhooks (PR-J)

- Migration 008 adds `users.subscription_status` (mirrors Stripe's
  `Subscription.status`). The billing webhook now handles
  `invoice.payment_failed` and the full status-transition matrix on
  `customer.subscription.{created,updated,deleted}`: a failed charge
  sets `past_due`, fires a "payment failed — update your card" email
  **once per dunning cycle** (debounced on the status flag), and
  records `billing.subscription.payment_failed` +
  `billing.dunning_email_sent` audit events. The paid tier is kept
  during Stripe's retry window (`past_due` / `incomplete`); recovery
  back to `active` re-derives the tier and records
  `billing.subscription.recovered`; a terminal status (`canceled` /
  `unpaid` / `incomplete_expired`, or the `.deleted` event) drops the
  tier to Free with `billing.subscription.canceled`. An unknown Stripe
  status leaves the tier untouched (recorded, not acted on). New
  `app/templates/emails/dunning.{html,txt}`. `GET /api/v1/auth/me` now
  returns `subscription_status` so the dashboard can surface a
  payment-issue banner.

### Added — Email internationalisation (PR-i18n-3)

- Transactional email (verification, password-reset, account-deleted,
  the PR-J dunning notice) is now localised. `app/core/email.py` gains
  `render_email(stem, *, locale, **ctx) -> (subject, html, text)` — one
  entry point backed by a per-locale Jinja `Environment`; the eight
  `app/templates/emails/*.{html,txt}` templates use `{% trans %}` blocks
  and `<html lang="{{ locale }}">`. Subject lines live in `EMAIL_SUBJECTS`
  marked with `N_(...)` for extraction. German catalog updated; the
  per-route ad-hoc email Jinja envs are gone.
- Migration 009 adds `users.preferred_lang` (`de` / `en`; NULL = use
  `LANG_DEFAULT`). Seeded at `/register` from the locale the user signed
  up in. `/forgot-password`, `/resend-verification` and the deletion
  confirmation render in `preferred_lang` if set, otherwise the request
  locale; the dunning mail (fired from a Stripe webhook with no request
  context) reads `preferred_lang` directly.
- `PUT /api/v1/auth/account/language` (Bearer; body
  `{"preferred_lang": "de"|"en"}`, `422` on anything else) lets a user
  change it; surfaced as an "Email language" picker on `/dashboard`.
  `GET /api/v1/auth/me` now returns `preferred_lang`. The web-UI locale
  is unaffected — it stays URL-prefix driven (no cookie); a sticky
  web-UI preference for logged-in users is a tracked follow-up.

### Added — Cloud-Edition pre-launch hardening (NEU-B.3 b/c.1)

- **Email verification** (NEU-B.3 slice b): Migration 006 adds
  `users.email_verified_at`. JWT verify-token bound to email-at-
  issuance (`eat` claim), 7-day TTL. `POST /auth/verify-email` +
  `POST /auth/resend-verification` (auth-required to avoid spam-
  vector). Fire-and-forget at register-time. New email + landing
  page templates.
- **Account deletion self-service, free path** (NEU-B.3 slice c.1):
  `DELETE /api/v1/auth/account` with three-field re-confirmation
  (`password` + `confirm_email` + `confirm_word=='DELETE'`). Last-
  admin guard (409). Cascade: ApiKey CASCADE, FileJob/UsageRecord
  SET NULL, audit-events SET NULL on actor. Confirmation email after
  commit. Stripe-touched accounts return 409 directing to
  `privacy@filemorph.io` until the paid-path tax-retention flow
  (slice c.2 — HGB §257, AO §147) ships.

### Added — Internationalisation completeness (post-pivot polish)

- **Impressum fully translated.** `app/templates/impressum.html` was
  previously German-only with a small EN preamble explaining why the
  body stayed German. Now every section heading + prose paragraph
  flows through `{{ _('…') }}`; only the legally-binding § references
  (§ 5 DDG, § 19 UStG, § 139c AO, § 18 (2) MStV, § 36 VSBG) and the
  operator's name + address stay verbatim. The Imprint is reachable
  in English at `/en/imprint` (the locale alias for `/impressum`,
  resolved via `_PATH_ALIASES` in `app/core/i18n.py`); footer + language
  switcher route through `localized_url`, which collapses `/imprint`
  back to the canonical `/impressum` on a DE-locale switch.
- **Admin Cockpit fully i18n'd.** `app/templates/cockpit.html` carried
  0 of 213 lines through `_()` — every heading, dropdown label, table
  header, and modal chrome string is now wrapped, with 35 new German
  translations.
- **JS-side i18n catalogue.** `app/core/i18n.py::_js_i18n_strings` is
  the new single source of truth for runtime strings the front-end
  needs (`Convert` / `Compress` button labels, validation alerts, the
  dynamic logged-in nav `Dashboard / Sign Out`, …). Translated per
  request and JSON-encoded into `window.FM_I18N` via a
  `<script type="application/json" id="fm-i18n-strings">` block in
  `base.html`. Eight JS files (`app.js`, `auth.js`, `dashboard.js`,
  `login.js`, `register.js`, `forgot-password.js`, `pricing.js`,
  `cockpit.js`, `cockpit-metrics.js`) read from there instead of
  hardcoding English literals. `auth.js` also derives the active
  locale prefix from `<html lang>` so dynamic nav links keep the
  user in their currently-active locale namespace.
- **Sitemap hreflang.** `/sitemap.xml` now emits one `<url>` block per
  (route × locale) combination — five base routes × three variants
  (x-default + de + en) = 15 entries on a Community deployment — each
  carrying its full `<xhtml:link rel="alternate" hreflang="…">` siblings
  list. The impressum/imprint alias is honoured end-to-end (the EN
  alternate of `/impressum` is `/en/imprint`, matching the footer +
  language-switcher behaviour). Without this, Google indexed locale
  variants as duplicate content; with it, they're declared siblings.

### Hardened — Scope-guard deny-by-default + 4-layer parity

- **Strategic-doc filename patterns now deny-by-default.**
  `.githooks/pre-commit::INTERNAL_PATHS` was a literal blocklist of
  13 specific filenames; a future `docs/foo-strategy.md` or
  `docs/q3-roadmap.md` with a fresh name would have slipped past the
  hard gate. The rule is widened to a pattern set: `*-strategy.md`,
  `*-plan.md`, `*-roadmap.md`, `*-internal.md`, `*-runbook.md`,
  `marketing-*.md`, `persona-*.md`, `competitive-*.md`,
  `engineering-pm-*.md`, `business-case-*.md`, `sprint-*.md`,
  `launch-*-tracker.md`, `launch-*-snapshot.md`,
  `launch-*-readiness.md`. Synced into `.githooks/pre-push` and into a
  new "Block strategic / business-internal docs" step in
  `.github/workflows/scope-guard.yml` so a `--no-verify`-bypassed
  commit still fails the server-side gate.
- **Notify-Ops + Article 28/30 compliance templates whitelisted.**
  `.github/workflows/notify-ops.yml` legitimately references
  `OPS_REPO_DISPATCH_PAT` (the secret name; value lives in GitHub
  Secrets); the three compliance templates `dpa-tom-annex.md`,
  `records-of-processing-template.md`, and
  `commercial-license-agreement-template.md` legitimately carry the
  operator's legal address as part of the Art. 28 processor identity.
  Both groups are now in the `ALLOW_RE` allowlist so future edits
  don't trip the hook (see commits `147d1a4` + `4e33249`).

### Added — Project hygiene (Kleinkram-cleanup sprint)

- **Deprecated stdlib / Starlette / Stripe APIs replaced.** Eliminates
  the 14 DeprecationWarnings emitted on every test run:
  `HTTP_413_REQUEST_ENTITY_TOO_LARGE → HTTP_413_CONTENT_TOO_LARGE`,
  `HTTP_422_UNPROCESSABLE_ENTITY → HTTP_422_UNPROCESSABLE_CONTENT`
  (Starlette 0.40 rename), `stripe.error.SignatureVerificationError →
  stripe.SignatureVerificationError` (stripe-python 12.x flat
  namespace), `datetime.utcnow() → datetime.now(timezone.utc)` in
  `scripts/launch_gate_check.py` (PEP 668).
- **SPDX license header on every .py file.** Project convention from
  CLAUDE.md applied to the 41 source files still missing the
  `# SPDX-License-Identifier: AGPL-3.0-or-later` line. Helps SBOM
  tooling (CycloneDX, Scancode) attribute licence at file granularity.
- **Container hardening — defence in depth on the existing non-root
  user.** `docker-compose.yml` adds `security_opt:
  [no-new-privileges:true]` (blocks setuid-style escalation inside the
  container) and `cap_drop: [ALL]` (the app needs no Linux
  capabilities — port 8000 is unprivileged, no `CAP_NET_RAW` or
  `CAP_DAC_OVERRIDE` required by any converter). `read_only: true` +
  `tmpfs /tmp` is staged as commented opt-in for operators who want
  the stronger guarantee.
- **`.env.example` env-var discoverability.** Three missing knobs
  (`LANG_DEFAULT`, `SECURITY_CONTACT_EMAIL`, `SMTP_FROM_NAME`,
  `SMTP_REPLY_TO`) added; `SMTP_USER`/`SMTP_FROM` renamed to
  `SMTP_USERNAME`/`SMTP_FROM_EMAIL` to match the pydantic-settings
  attribute stems. `CORS_ORIGINS` default flipped from `*` to
  `http://localhost:8000` (the middleware refuses to combine `*` with
  `allow_credentials=true` anyway). `app.app_version` bumped to PEP 440
  dev marker `1.1.0.dev0`; `pyproject.toml::version` kept in sync.
- **CI / scope-guard workflows: concurrency groups.** `ci.yml`,
  `scope-guard.yml`, `verapdf.yml` now declare `concurrency:
  cancel-in-progress: true` on non-main / non-develop refs. A new push
  on the same PR branch cancels superseded queued runs; main /
  develop runs always complete (branch-protection gates).
- **PT-011 hardened.** `/api/v1/health` strips down to `{"status":
  "ok"}` — no version, no `ffmpeg_available` flag (see Security
  section above). `/api/v1/ready` carries the operational state.

### Added — Supply-chain hygiene (PR-S)

- All GitHub Actions `uses:` references pinned to a full 40-character
  commit SHA (with the `# vX.Y` comment Dependabot tracks), instead of
  mutable tags.
- `.github/dependabot.yml` (NEW): weekly update PRs for three
  ecosystems — `pip` (grouped minor/patch), `github-actions` (grouped),
  and `docker` (base-image digest) — so the manual pins stay current
  without manual chasing.
- Dockerfile base image pinned by `@sha256:` digest, with the
  `python:3.12-slim` tag kept in a trailing comment for Dependabot's
  `docker` updater.
- Every workflow declares an explicit least-privilege `permissions:`
  block for `GITHUB_TOKEN` (`contents: read` by default; `contents:
  write` only where a release-asset upload needs it; `{}` for the
  cross-repo-dispatch job that uses a separate PAT).
- `tests/test_supply_chain_hygiene.py` (NEW): regression guards that
  fail CI if an action pin reverts to a tag, the Dockerfile loses its
  digest, a workflow ships without a `permissions:` block, or
  `dependabot.yml` stops covering a pinned ecosystem.

### Operations

- Docker base image now bundles `ghostscript` so the PDF/A re-render
  path is on by default for self-hosters of the official image.
- CI workflow installs `ghostscript` so the converter exercises the
  full path under test.

### Test coverage

`tests/` grew from ~260 to **627 collected** (15 Windows-skipped —
the PDF/A test modules; see test_pdfa.py docstring for the qpdf
DLL-load conflict; Linux CI + production are unaffected). The 32
post-trust-foundation additions cover the i18n catalogue end-to-end
(FM_I18N JSON blob present + locale-resolved per request), the
impressum/imprint locale-alias mapping (forward + reverse), the
sitemap hreflang invariants, and the expanded scope-guard regex
positives + public-doc negatives.

---

## [1.0.2] — 2026-04-20

### Security
- **PT-002:** `validate_api_key()` now uses a `hmac.compare_digest` loop that always
  iterates all stored hashes — eliminates timing-attack vector on key enumeration
- **PT-008:** WeasyPrint `url_fetcher` blocked for Markdown→PDF conversion — prevents
  SSRF via embedded images or CSS `@import` in user-supplied Markdown
- **GDPR:** Temp files now use UUID stems instead of original filenames — eliminates
  PII from filesystem paths, OS logs, and crash dumps
- **CVE-2024-28219:** Raised `Pillow` minimum to `>=10.3.0`
- **CVE-2024-53981:** Raised `python-multipart` minimum to `>=0.0.18`

---

## [1.0.1] — 2026-04-19

### Fixed
- `TemplateResponse` call updated for Starlette 1.0 API compatibility
  (`TemplateResponse(request, name)` instead of deprecated `TemplateResponse(name, {"request": request})`)

### Added
- `dev.ps1` — Windows developer startup script: auto-creates venv, installs dependencies,
  generates API key on first run, starts uvicorn with `--reload`. Searches Windows Registry
  for Python installations so it works regardless of PATH configuration.
- `create-shortcut.ps1` — creates a Desktop shortcut that launches `dev.ps1` via PowerShell

### Changed
- GitHub Actions CI updated to Node.js 24 (Node.js 20 deprecated June 2026)

---

## [1.0.0] — 2026-04-15

### Added

**Converters**
- Image: HEIC/HEIF, JPG, PNG, WebP, BMP, TIFF, GIF, ICO — all combinations via Pillow + pillow-heif
- Documents: DOCX → PDF, DOCX → TXT, TXT → PDF, PDF → TXT
- Markdown: MD → HTML, MD → PDF (via WeasyPrint)
- Spreadsheets: XLSX ↔ CSV, CSV ↔ JSON
- Audio: MP3, WAV, FLAC, OGG, M4A, AAC, WMA, Opus — all combinations via pydub/ffmpeg
- Video: MP4, MOV, AVI, MKV, WebM, FLV, WMV — all combinations via ffmpeg-python

**Compression**
- Image quality compression: JPG, PNG, WebP, TIFF (Pillow quality parameter)
- Video CRF compression: MP4, MOV, AVI, MKV, WebM (ffmpeg libx264 CRF)

**REST API**
- `POST /api/v1/convert` — file conversion with optional quality parameter
- `POST /api/v1/compress` — quality-based file compression
- `GET /api/v1/formats` — list of all supported format pairs
- `GET /api/v1/health` — health check with ffmpeg availability flag
- API key authentication via `X-API-Key` header (SHA-256 hashed storage)
- Rate limiting: 60 requests/minute per IP (slowapi)
- CORS middleware (configurable origins)
- Upload size limit (configurable, default 100 MB)

**Web UI**
- Dark-mode interface with TailwindCSS
- Drag & drop file upload
- Dynamic format dropdown (shows only compatible targets for the uploaded file)
- Quality slider
- API key input
- Download result button
- Convert / Compress mode toggle

**Operations**
- Docker image with ffmpeg and libheif included
- `docker-compose.yml` with health check and data volume
- GitHub Actions CI (lint + test on every push)
- GitHub Actions Docker workflow (build + push to GHCR on version tags)
- `scripts/generate_api_key.py` — CLI key generator

**Documentation**
- `README.md` with UI mockup, quickstart, API examples
- `docs/installation.md` — Windows and Linux installation guide
- `docs/api-reference.md` — complete API reference with code examples (Python, JS, PHP, C#)
- `docs/self-hosting.md` — production deployment, nginx, SSL, internal network
- `docs/formats.md` — all formats with quality notes and use cases
- `docs/development.md` — project structure, adding converters, release process
- `CONTRIBUTING.md`
