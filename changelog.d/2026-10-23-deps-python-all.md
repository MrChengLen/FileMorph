### Changed — dependency batch: FastAPI 0.154, Pydantic 2.14, SQLAlchemy 2.1.5 and eight smaller updates

Dependabot's weekly `python-all` group (#259) lands in one pull request, with
`requirements.lock` recompiled once. What the image ships now:

- **FastAPI 0.154.0** (from 0.142.2). In between, FastAPI changed how it reads
  request data. One change shows in FileMorph's routes: a file part with no
  file in it, which a plain browser form sends for an empty file input, now
  counts as missing. The upload routes answer it with the generic 422 for a
  missing field instead of their own message about the file name, and a batch
  that also carries real files leaves it out. FileMorph's pages only send
  files the user picked, and a missing file or an empty quality field gets the
  same answer as before. The
  automatic OpenTelemetry exporter setup now needs
  `FASTAPI_OTEL_AUTO_CONFIGURE=true`; the image ships no OpenTelemetry SDK
  either way. 0.154.0 is the version Dependabot proposed under its three-day
  cooldown; the newest release, 0.161.1, was younger.
- **Pydantic 2.14.1** (from 2.13.5, with pydantic-core 2.50.1) and
  pydantic-settings 2.16.1 (from 2.15.0).
- **SQLAlchemy 2.1.5** (from 2.1.4) and asyncpg 0.32.0 (from 0.31.0), on the
  account database path. 2.1.5 fixes a bug on the asyncio path FileMorph uses:
  a connection the pool closed after its task was cancelled twice, as AnyIO
  cancel scopes do, stayed in the pool and failed on its next checkout. 2.1.5
  rather than 2.1.6, which was younger than the cooldown.
- pillow-heif 1.8.1 (security fixes in the libheif it bundles, see the
  separate entry), cryptography 50.0.2 (its wheels bundle OpenSSL 4.0.3),
  Markdown 3.11.2 (attribute names in fenced code blocks are sanitized, and an
  unterminated end tag no longer drops the rest of the document) and pikepdf
  10.17.0.

Development tools: ruff 0.17.1, which reformats nothing, and uv 0.13.4
(`requirements-uv.lock` recompiled with it, see the separate entry); the
lockfiles come out in the same format.
