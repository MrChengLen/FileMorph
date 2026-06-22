# `app/ee/` — Enterprise Edition (commercial-only)

**License: `LicenseRef-FileMorph-Commercial` — NOT AGPL-3.0.**

Everything in this directory is licensed **solely** under
[`COMMERCIAL-LICENSE.md`](../../COMMERCIAL-LICENSE.md), as an explicit exception
to the AGPL-3.0 that covers the rest of this repository. This is the
GitLab-CE/EE / open-core pattern: the source is **visible** (for transparency,
security audit, and review) but it is **not open source** — you may not use,
run, modify, copy, or deploy it without a commercial license.

The AGPL engine (`app/converters/`, `app/compressors/`, `app/core/`, …) works
fully without anything here. Every EE feature is **gated to be inert** unless
its environment is configured — exactly like the existing Stripe/SMTP/audit
"inert without env vars" pattern — so a default self-host build never executes
EE code.

`filemorph.io` (the copyright holder, sole author) operates these modules under
the *operator's reservation* in `COMMERCIAL-LICENSE.md`.

## What lives here

| Path | Feature |
|---|---|
| `app/ee/ai_ops/` | AI file operations — PII redaction (local), and (later) generative document operations. Paid-only add-on for hosted customers. |

## Rules for code in this directory

- SPDX header on every file: `# SPDX-License-Identifier: LicenseRef-FileMorph-Commercial`.
- Cost-revealing values (model IDs, token math, cost→credit mapping) live in
  **private environment**, never in source — client- and repo-facing surfaces
  are credit-denominated only. See `docs-internal/ki-integration-konzept.md`.
- EE code may import the AGPL engine; the engine must never import `app.ee.*`
  at startup — only the gated, lazily-loaded feature routes may.
