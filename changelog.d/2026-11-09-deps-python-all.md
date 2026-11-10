### Changed — dependency batch: python-multipart 0.0.33, Markdown 3.11.3, Pydantic 2.14.3 and nine smaller updates

Dependabot's weekly `python-all` group (#325) lands in one pull request, with
`requirements.lock` recompiled once. Every version has passed the three-day
cooldown in `.github/dependabot.yml` and is the newest release its version
range allows. What the image ships now:

- **python-multipart 0.0.33** (from 0.0.32), the parser Starlette reads every
  form and upload with. It matches the opening boundary in one step and
  dispatches URL-encoded fields faster. For a `Content-Type` with parameters
  it now returns the media type in lower case, as it already did without
  parameters, so a request sent as `Multipart/Form-Data; boundary=…` is read
  as a form instead of arriving empty and failing with a 422. FileMorph's check
  that form bodies are UTF-8 already ignored the case. The new field limits
  for URL-encoded forms and the fixes to Content-Transfer-Encoding decoding
  concern python-multipart's own `FormParser`, which Starlette does not use.
- **Markdown 3.11.3** (from 3.11.2), which turns uploaded Markdown into HTML and
  PDF. Many reference definitions in a row, a long run of `#` followed by text
  on a heading line, and many unclosed HTML comments no longer take quadratic
  time, and text between backticks that do not match is no longer lost. Links
  in angle brackets now accept any scheme written with `://`, such as
  `<ssh://example.org>`, not only HTTP and FTP. That adds nothing raw HTML
  could not already do: Markdown passes `<a href>` tags through unchanged, and
  the PDF renderer fetches nothing for a link.
- **Pydantic 2.14.3** (from 2.14.1, with pydantic-core 2.50.4) and
  pydantic-settings 2.16.2 (from 2.16.1). Pydantic 2.14.2 fixes two medium
  advisories in which validation let through data that did not match its
  declared type: the keys of extra data in JSON validation
  (GHSA-qpmf-fgh3-ff25), and aliased fields of a `TypedDict` or dataclass
  that allows extra data (GHSA-3r8g-cqwr-jr29). Both need types that keep
  extra data (`extra="allow"`), which FileMorph does not define. 2.14.2 also
  makes JSON validation treat a key that matches only an unused alias or field
  name as extra data; FileMorph validates no JSON text directly, since FastAPI
  decodes a request body before validating it.
- **SQLAlchemy 2.1.8** (from 2.1.6), on the account database path: ORM and
  engine bug fixes from 2.1.7, which also checks the `ondelete` phrase of a
  foreign key more strictly; FileMorph's are plain `CASCADE` and `SET NULL`.
  Since 2.1.8, every file of a release carries a provenance attestation.
- OpenTelemetry API 1.45.2 (from 1.45.1): the trace-context propagator no
  longer parses a `traceparent` header longer than 512 characters. FastAPI
  reads that header only when an OpenTelemetry tracer provider is configured,
  and the image ships no OpenTelemetry SDK.
- dnspython 2.9.2 (from 2.9.0): a zone file with a crafted WKS record no longer
  exhausts memory. FileMorph never loads dnspython.
- Stripe 15.6.2 (from 15.6.1): the SDK's own CA bundle shrinks to the 12 roots
  that Stripe's domains chain to, and the emSign ECC Root CA - G3 is among the
  roots dropped. FileMorph's Stripe calls verify against certifi's bundle
  instead, which dropped that root in 2026.10.19.

Development tools: ruff 0.17.4, which reformats nothing, and uv 0.13.7
(`requirements-uv.lock` regenerated), which writes the lockfiles in the same
format. pytest 9.2.0 and pytest-asyncio 1.4.1.post1 only raise the floors: the
lockfile does not pin development tools, so CI already ran these releases.
