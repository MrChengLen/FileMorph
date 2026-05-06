# Tech-Stack Rationale

Why FileMorph picks the libraries it picks. This doc is for OSS
contributors and self-hosters who want to read or extend the code —
not a marketing pitch and not a tutorial. Each library gets three to
five lines: **what** it does in this project, **why** it was chosen,
and the closest **alternative** (with the trade-off). Specific
versions live in `requirements.txt`; that file is the source of truth
and changes faster than this one.

If you are looking for **how to install** the stack, see
[`installation.md`](installation.md). For **how to deploy**, see
[`self-hosting.md`](self-hosting.md). For **which converter handles
which format**, see [`formats.md`](formats.md). The internals of the
plugin registry live in `app/converters/`.

## Reading Guide

Three constraints shape every choice on this page, and they are
worth stating up front so the rationales make sense:

1. **AGPLv3 license-compatibility.** FileMorph is published under
   AGPLv3 with a commercial-relicensing option. A dependency licensed
   under GPLv3-only is *not* compatible — it would force the project
   to drop the dual-license offering. MIT / BSD / Apache-2.0 / LGPL /
   AGPLv3 are all fine. This rules out a handful of otherwise
   attractive libraries; where that happens it is called out.
2. **Async-first.** The application is FastAPI on Uvicorn, which
   means the request handler runs inside an `asyncio` event loop. A
   synchronous library that does meaningful CPU work (image encoding,
   PDF rendering, FFmpeg invocation) cannot run in the handler
   directly — it has to be moved off the loop with
   `asyncio.to_thread(...)`. The libraries below are picked with this
   constraint in mind.
3. **Self-host-able on a single Hetzner box.** A self-hoster who
   pulls the repo, sets a few env-vars and runs Docker Compose
   should get a working install. Dependencies that demand a
   heavyweight side-car (Redis, Elasticsearch) are deferred to the
   "Future Considerations" section rather than baked into the
   default deploy.

If you spot a contradiction between this doc and the code, the code
wins — please open a PR to fix the doc.

---

## Core Web Framework

The HTTP-and-templating layer is intentionally boring. The interesting
part of FileMorph is what happens after the request arrives (the
converter pipeline); the routing layer just needs to deliver bytes
in and out, render a few admin templates, and validate inputs at the
boundary.

| Library | What it does | Why this | Alternative |
|---|---|---|---|
| **FastAPI** | HTTP routing, dependency injection, request/response models | Async-native, Pydantic-first, OpenAPI auto-generated. Lets the converter routes stay terse. | Flask (synchronous, no schema-first), Starlette (lower-level, no DI) |
| **Uvicorn[standard]** | ASGI server in front of FastAPI | The `[standard]` extras pull in `httptools` + `websockets` for the throughput path the FastAPI docs recommend. | Hypercorn (HTTP/2-capable), Daphne (Django-ASGI heritage) |
| **python-multipart** | Parses `multipart/form-data` uploads | FastAPI requires it for `File()` parameters. No direct import in the app code — pulled in transitively. | None practical; multipart is a wire-format, not a design choice. |
| **Jinja2** | Server-side HTML for `/`, `/pricing`, `/dashboard`, `/cockpit` | Deliberate: no React/Vue build pipeline, CSP-friendly, fast time-to-interactive. The few client-side interactions live in plain `app/static/js/*.js`. | Mako (faster, less ergonomic), Chevron (logic-less Mustache — too restrictive for our admin views) |

**Note on the no-SPA choice.** FileMorph's UI is a small set of forms
plus a converter widget. A bundler would dominate the maintenance
budget for a feature surface that doesn't need it. Adding React later
is a one-page swap if it ever pays off; ripping out a build pipeline
once it's in is harder.

---

## Validation & Settings

Pydantic shows up in two distinct roles: as the schema layer for
request and response bodies (where it's effectively the FastAPI
default), and as the configuration layer that reads environment
variables into a typed `Settings` object. Both are deliberate single
points of validation — the application code below the boundary
trusts the types it gets and does not re-validate.

| Library | What it does | Why this | Alternative |
|---|---|---|---|
| **Pydantic v2** | Request/response schemas, automatic 422 validation errors | The Rust-backed `pydantic-core` is roughly an order of magnitude faster than v1 and is the model layer FastAPI is built around. | marshmallow (older, less FastAPI integration), attrs (data-class only, no validation) |
| **pydantic-settings** | Loads `Settings(BaseSettings)` from `.env` + environment | Canonical settings live in `app/core/config.py`. Type-checked, single source of truth for env-vars. | dynaconf (more features but heavier), environs (thin wrapper around os.environ) |

The full Cloud-Edition env-var landscape (`DATABASE_URL`,
`JWT_SECRET`, `STRIPE_*`, `SMTP_*`, `APP_BASE_URL`) lives in
`app/core/config.py`. `.env.example` currently lists only the
file-only-edition variables; expanding it is a tracked follow-up.

A note on validation philosophy: FileMorph validates at the
*boundary* (where bytes arrive from outside) and trusts the types
internally. Adding redundant runtime checks inside trusted code is
discouraged — it's the kind of cargo-cult defensiveness that makes
codebases hard to read without making them safer.

---

## File Processing

The biggest dependency cluster — every converter is a thin
adapter over a battle-tested library. The plugin registry
(`app/converters/registry.py`) discovers them; new formats add a
single `@register("src", "tgt")` decorator without touching the core.

| Library | What it does | Why this | Alternative |
|---|---|---|---|
| **Pillow** | Image read/write/convert (JPG/PNG/WebP/AVIF and friends) | The de-facto Python image library. Wide format support, predictable memory profile, BSD-style license. | ImageMagick CLI (subprocess overhead, harder to sandbox), Wand (ImageMagick binding — heavier deploy) |
| **pillow-heif** | HEIC input (Apple Photos export) | Ships as a separate wheel rather than a Pillow-bundled plugin because of LGPL-vs-MIT licensing on the underlying `libheif`. Adding it as a plugin keeps the Pillow side license-clean. | pyheif (older, less maintained) |
| **python-docx** | DOCX read/write | Microsoft OOXML reference implementation in Python. | python-pptx (PPTX-only, complementary), aspose-words (commercial) |
| **pypdf** | PDF merge / split / page extraction | Pure-Python, BSD-licensed, AGPLv3-compatible. Active fork of the PyPDF2 lineage. | PyPDF2 (deprecated upstream), pdfplumber (read-only, extraction-focused), PyMuPDF (faster but ~50 MB native binary) |
| **reportlab** | PDF generation (TXT→PDF) | BSD-licensed Open Source Edition; the right tool when generating a PDF from scratch rather than transforming HTML. | WeasyPrint (HTML→PDF — different use-case, kept in parallel), fpdf2 (lighter, fewer features) |
| **WeasyPrint** | HTML/CSS → PDF | Used for any HTML-source PDF output (e.g. Markdown → HTML → PDF). SSRF-hardened in `app/converters/document.py` via `url_fetcher=_deny_url_fetcher`. | wkhtmltopdf (deprecated; QtWebKit-based), Puppeteer/Playwright (Node.js + headless Chrome — much heavier) |
| **markdown** | Markdown → HTML pre-processing for the WeasyPrint pipeline | Stable, predictable output; the dialect FileMorph ships matches what most users expect from a Markdown converter. | mistune (faster but a different feature set), markdown-it-py (CommonMark-strict) |
| **openpyxl** | XLSX read/write | Pure Python, no Excel install required, predictable on Linux containers. | pandas (heavy dataframe overhead for simple reads), xlsxwriter (write-only) |
| **ffmpeg-python** | Wrapper around the FFmpeg CLI for audio/video conversion | The FFmpeg binary itself is the workhorse; this library just gives it a typed Python surface. The binary must be available in the deployment image (Dockerfile installs it). | moviepy (heavier abstraction, slower), direct `subprocess.run` (no type hints, more boilerplate) |
| **pydub** | Audio conversion (MP3/WAV/OGG/...) | Wraps FFmpeg/libav for the audio-only path. Simpler API than driving FFmpeg directly when you don't need video. | librosa (analysis-focused, heavier), soundfile (libsndfile binding, narrower codec coverage) |

**Event-loop discipline.** Every C-binding call (FFmpeg via
`ffmpeg-python`, WeasyPrint, `pypdf`, large Pillow saves) runs
through `asyncio.to_thread(...)`. A blocking call inside the FastAPI
event loop is a single-user denial-of-service.

**Why so many file libraries?** Each format family has a different
shape: images are pixel grids, PDFs are paginated stream objects,
DOCX is XML inside a zip, audio is samples plus metadata. There is
no single library that handles all of them well, and trying to use
one generic tool (ImageMagick, Pandoc, LibreOffice headless) means
inheriting that tool's idiosyncrasies for every conversion. The
adapter-per-format approach keeps each path debuggable in isolation.

**The plugin pattern.** `app/converters/registry.py` exposes a
`@register("src_ext", "tgt_ext")` decorator. A new converter is one
file, one decorator, one function with the signature
`convert(input_path, output_path, **kwargs)`. The dispatcher in
`app/api/routes/convert.py` looks up the right callable by
extensions; the core does not need to know which library does the
work. This is also how a self-hoster adds a custom converter without
forking — drop a module into `app/converters/`, and the registry
picks it up at import time.

**SVG and exotic formats.** SVG support relies on the system Cairo
stack pulled in by WeasyPrint; FileMorph does not ship a native SVG
manipulation library. If you need to *generate* SVG programmatically,
that's an open feature request, not a deficiency in the existing
stack — file an issue rather than reaching for a heavyweight
dependency.

---

## Limits & Infrastructure

| Library | What it does | Why this | Alternative |
|---|---|---|---|
| **python-dotenv** | Loads `.env` for local development | In production `pydantic-settings` reads directly from the process environment (Docker injects the values). `.env` is convenience for the dev loop. | `os.getenv` only (no `.env` support), direnv (shell-side, not Python) |
| **slowapi** | Rate-limit middleware (10 req/min on `/api/v1/convert` and `/api/v1/compress`) | In-memory storage. Single-instance only — adequate for the current deployment. Multi-instance would require swapping in a Redis backend. | fastapi-limiter (Redis-mandatory), starlette-context-rate-limit (lighter but more glue) |

The shared limiter instance lives in `app/core/rate_limit.py`. Tests
disable it via the session-scoped `disable_rate_limiting` fixture in
`tests/conftest.py` — never remove that fixture, the limiter
accumulates hits across the test session and tests 11+ would start
returning 429.

---

## Auth & DB (Cloud Edition)

The Cloud-Edition stack — what makes filemorph.io a SaaS rather
than just a CLI tool. Every library here is also useful for a
self-hoster who wants accounts and email instead of a static API-key
file. The split-edition design is the point: a self-hoster who only
needs a converter behind an internal load balancer can leave
`DATABASE_URL` empty and run the file-only edition; a self-hoster
who wants user accounts, billing, or transactional email enables the
Cloud-Edition pieces by setting the right env-vars. Both share the
same code-base.

| Library | What it does | Why this | Alternative |
|---|---|---|---|
| **SQLAlchemy[asyncio] 2.x** | ORM with native async API | The 2.x rewrite removed the awkward `sync_session.run_sync(...)` shim. Async all the way down means no thread-pool tax on DB-heavy endpoints. | Tortoise-ORM (Django-style API, smaller community), encode/databases (low-level Query Builder, no ORM) |
| **Alembic** | Schema migrations | The de-facto migration tool for SQLAlchemy. `alembic.ini::sqlalchemy.url` is intentionally empty — `alembic/env.py` reads `DATABASE_URL` from the environment so the same migrations work in dev / staging / prod. | yoyo-migrations (DB-agnostic, but no ORM binding), Django migrations (Django-only) |
| **asyncpg** | Async PostgreSQL driver | Cython-compiled, the fastest Python Postgres driver by a wide margin. Connect via `postgresql+asyncpg://...`. | psycopg3-async (sync+async unified — slightly slower on the pure-async path), aiopg (psycopg2-wrapper, deprecated) |
| **python-jose[cryptography]** | JWT encode/decode | The `[cryptography]` extra pulls in the modern `cryptography` backend rather than the legacy pure-Python one. | PyJWT (lighter; we'd lose a few algorithm options we don't currently use), authlib (full OAuth2 stack — overkill for JWT-only) |
| **bcrypt** | Password hashing | Used in `app/core/auth.py` for user-password verification. Adaptive cost factor; the work-factor is the standard knob to dial as hardware gets faster. NIST-approved. | argon2-cffi (winner of the Password Hashing Competition; bcrypt is "good enough" and ubiquitous), passlib (wrapper library — extra layer of indirection without a strong reason here) |
| **email-validator** | RFC-5321/5322 validation behind Pydantic's `EmailStr` | Pulls in by default; gives meaningful 422 errors at the boundary instead of silently letting a malformed address into Stripe or Zoho. | stdlib `email.utils` (lax — accepts addresses that bounce), pyIsEmail (slower) |
| **aiosmtplib** | Async SMTP for transactional email (Zoho) | Lives in `app/core/email.py`. The TLS mode is chosen by port: `465` → implicit SSL from the first byte, anything else (we use `587`) → plain connect + STARTTLS. Hetzner Cloud blocks outbound port 465 by default for new accounts, so `587` is the path of least friction. | stdlib `smtplib` (sync-only — would block the event loop on every send) |

**API-key authentication** for the file-only edition lives in
`app/core/security.py` and uses SHA-256 + `hmac.compare_digest` (no
bcrypt). The constant-time comparison is critical and intentional;
do not "optimize" the loop to short-circuit.

**Why two hashing schemes?** API keys and passwords have different
threat models. An API key is a high-entropy random token (256 bits
from `secrets.token_urlsafe`) that the user never types — SHA-256 is
fine because the input space is already uncrackable. A password is
low-entropy human-chosen text that the user *does* type — bcrypt's
adaptive cost factor makes the per-guess cost expensive enough that
offline brute-force is impractical even on leaked hashes. Mixing
the two would either over-secure the keys (slow auth on hot paths)
or under-secure the passwords. They live in separate modules
deliberately.

---

## Payments

| Library | What it does | Why this | Alternative |
|---|---|---|---|
| **stripe** | Stripe Python SDK — Checkout sessions, webhook signature verification, Customer Portal | Stripe is the obvious default for a EU-hosted SaaS in 2026; the Python SDK is the canonical surface. Webhook signatures are verified via `stripe.Webhook.construct_event(...)`. | Paddle (Merchant of Record — handles EU VAT for you, but takes a higher cut; trade-off-discussion not duplicated here), LemonSqueezy (newer MoR, smaller reach) |

**Webhook coverage status.** `customer.subscription.*` and
`checkout.session.completed` are handled today.
`invoice.payment_failed` and `invoice.payment_succeeded` are not yet
wired in. Adding them is a tracked follow-up; they are needed before
serious dunning behaviour can be implemented.

---

## License Map

Because FileMorph is AGPLv3 with a commercial-relicensing option,
the license of every direct dependency matters. The table below
captures what's currently in the tree; if you add a new dependency,
update this row in the same PR.

| Library | License | Notes |
|---|---|---|
| FastAPI, Starlette, Pydantic, Pydantic-Settings | MIT | Permissive. |
| Uvicorn, python-multipart | BSD-3-Clause | Permissive. |
| Jinja2, MarkupSafe | BSD-3-Clause | Permissive. |
| Pillow | HPND (BSD-style) | Permissive. |
| pillow-heif | Apache-2.0 (wrapper) over LGPL `libheif` | Wrapper is Apache-2.0; the underlying `libheif` is LGPL — separate-wheel install keeps the boundary clean. |
| python-docx | MIT | Permissive. |
| pypdf | BSD-3-Clause | Permissive (clean fork from PyPDF2's BSD heritage). |
| reportlab | BSD-3-Clause (Open Source Edition) | Commercial Plus edition exists but we use OSE. |
| WeasyPrint | BSD-3-Clause | Permissive. |
| markdown | BSD-3-Clause | Permissive. |
| openpyxl | MIT | Permissive. |
| ffmpeg-python | Apache-2.0 (wrapper) over FFmpeg (LGPL/GPL depending on build) | The Python wrapper is Apache-2.0; the FFmpeg binary itself can be built LGPL or GPL — use the LGPL build to keep AGPLv3-compatibility maximally clean. |
| pydub | MIT | Permissive. |
| python-dotenv | BSD-3-Clause | Permissive. |
| slowapi | MIT | Permissive. |
| SQLAlchemy, Alembic | MIT | Permissive. |
| asyncpg | Apache-2.0 | Permissive. |
| python-jose | MIT | Permissive. |
| bcrypt | Apache-2.0 | Permissive. |
| email-validator | The Unlicense / CC0 | Public-domain-equivalent. |
| aiosmtplib | MIT | Permissive. |
| stripe | MIT | Permissive. |

Everything in the current tree is either permissive (MIT, BSD,
Apache-2.0) or LGPL via a wrapper boundary. There is no GPLv3-only
or AGPLv3 dependency that would constrain downstream users. If a
future PR brings one in, this table is the place to flag it.

---

## Future Considerations

These libraries are **not** in `requirements.txt` today. They are
listed here so a reader knows what the planned trajectory looks like
without having to read the changelog backwards.

| Library | What it would do | When it lands |
|---|---|---|
| **boto3** (commented in `requirements.txt`) | S3- or R2-compatible object storage | When FileMorph needs to scale beyond a single instance. The current stateless design — files held in `BytesIO`, temp dirs cleaned in `finally` blocks — is adequate for one box. |
| **Redis** | Multi-instance rate-limit storage (slowapi backend), session storage | When FileMorph runs on more than one application container. Not currently wired in. |
| **prometheus-fastapi-instrumentator** | `/metrics` endpoint for Prometheus / Grafana | Planned for post-launch monitoring. |
| **PostHog or Plausible** (external services, not Python deps) | Product / web analytics — both are GDPR-friendly, both can self-host | When the product needs funnel analysis or conversion tracking beyond what the structured logs already give. |

---

## How to Add a New Library

The bar for new dependencies is "this earns its weight". The
workflow:

1. **Pin in `requirements.txt`** with a `>=` constraint. Strict
   pins (`==`) are reserved for libraries with known breaking
   changes between minor versions.
2. **Run `pip-audit -r requirements.txt`** — a new dependency must
   not introduce open High/Critical CVEs. The audit step is part of
   the CI pipeline (non-blocking, but reviewed).
3. **Add an entry to this file** under the right category — what,
   why, alternative. Future contributors will read this before they
   read the source.
4. **Write an integration test** in `tests/`. New libraries without
   tests do not get merged.
5. **License-check.** AGPLv3 is contagious for derivative works;
   GPLv3-only dependencies are **not** compatible with AGPLv3 and
   would force a license change. MIT, BSD, Apache-2.0 and LGPL are
   fine. When in doubt, ask before committing.

The project rule is explicit: don't add features beyond what the
task requires. That applies to dependencies too. A second PDF
library "because it might be faster" is the kind of bloat that
makes a six-month-old project feel like a six-year-old one. Reuse
first; add only when the existing stack genuinely cannot do the
job.

## Considered and Rejected

A short list of libraries that came up during design and were
deliberately *not* included, with the reason. This section exists
so the same arguments don't have to be relitigated every six months.

- **Pandas** — Considered for XLSX read/write. Rejected: too heavy
  for the simple read/write paths FileMorph actually uses, and pulls
  in NumPy as a transitive dependency. `openpyxl` covers the use
  case at a fraction of the install size.
- **PyMuPDF** — Considered for PDF operations. Faster than `pypdf`,
  but ships a ~50 MB native binary and historically had license
  ambiguity (parts of the older MuPDF heritage). `pypdf` is good
  enough for merge / split / page-extract, which is the entire PDF
  surface today.
- **wkhtmltopdf** — Considered for HTML→PDF. Rejected: upstream
  deprecated, security-uncertain, and based on an old QtWebKit fork.
  WeasyPrint is the maintained replacement.
- **Django** — Considered as the web framework. Rejected: synchronous
  request model would tax the file-conversion paths, and the ORM-
  centric design fits poorly with the largely stateless converter
  workload. FastAPI + SQLAlchemy gives the same ORM ergonomics
  without the synchronous tax.
- **PyJWT** — Lighter than `python-jose`. Considered for the JWT
  layer; the only differentiator is algorithm support, and there is
  no ongoing reason to switch. Listed here so a future PR proposing
  the swap has the prior context.

---

## See Also

- [`installation.md`](installation.md) — how to install the stack
- [`self-hosting.md`](self-hosting.md) — how to deploy
- [`development.md`](development.md) — local dev loop
- [`formats.md`](formats.md) — which converter handles which format
- `requirements.txt` — authoritative version pins
- `app/converters/` — the plugin registry
- `app/core/config.py` — the canonical Settings class
- `docs/security-overview.md` — security posture and self-hoster
  hardening checklist
