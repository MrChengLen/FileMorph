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
