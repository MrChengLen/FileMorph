# Sub-processors

A *sub-processor* is a third-party service that processes personal data on
behalf of the controller (you, when you self-host; us, when you use the
SaaS at filemorph.io). Article 28 GDPR requires you to disclose your
sub-processors to data subjects and to put a Data Processing Agreement
(DPA) in place with each one.

This document lists the sub-processors that a default FileMorph
deployment may touch, the data category each one receives, and the
toggle that disables it. **None of these are activated until the
corresponding feature is configured** — a Community Edition deployment
that runs anonymous conversions only contacts no sub-processors at all.

Self-hosters: copy this file into your own privacy documentation, prune
the rows that do not apply to your deployment, and add any additional
services you have integrated. The default fields are reproduced here as
a starting template, not as a binding statement about your deployment.

## Default-deployment sub-processor list

| Service | Purpose | Data category | Region | Toggle |
|---|---|---|---|---|
| **Hetzner Online GmbH** | Server hosting | Server access logs (IP, request time, URL, status, size) — written by the OS-level web server, not by the FileMorph application. | Frankfurt / Falkenstein, Germany (EU) | Inherent to the deployment; switch hosting provider to opt out. |
| **Cloudflare Inc.** | DDoS protection, edge caching, optional R2 storage | TLS-terminated request metadata; no request bodies. | Distributed (operator may set a regional preference). | Optional; remove the proxy and serve the origin directly. |
| **Stripe Inc.** | Payment processing (Cloud Edition only) | Customer email and an internal user identifier; card data is collected by Stripe directly and never reaches FileMorph. | United States (EU SCCs apply via Stripe DPA). | Disabled when `STRIPE_SECRET_KEY` is empty. |
| **Zoho Corporation B.V.** | Transactional email (password-reset, billing receipts) | Recipient address and the email body (reset link or receipt). | Frankfurt, Germany (EU). | Disabled when `SMTP_HOST` is empty. |
| **GitHub Inc.** | Source distribution and issue tracking | Public repository metadata only; not in the request path of any deployment. | United States. | Inherent to the open-source distribution model. |

## What FileMorph itself does NOT send out

The FileMorph application code, by design, never transmits user-uploaded
files, file contents, or filenames to any sub-processor. The only outbound
calls in the application code are:

- PostgreSQL queries to the configured database (Cloud Edition).
- SMTP submissions to the configured relay for password-reset and
  billing emails (Cloud Edition).
- Stripe Checkout-Session creation and webhook responses (Cloud Edition,
  paid tiers).

There is no analytics beacon, no telemetry endpoint, no "phone home" call,
and no third-party CDN for static assets — Tailwind, fonts, and the
Chart.js library used by the admin cockpit are all served from the
deployment's own origin.

## Adding a sub-processor

If you integrate an additional service (object-storage backend, external
auth provider, observability vendor), update this file in your fork and
publish the updated list to your data subjects before activating the
feature. Procurement reviewers and DPOs use this document as the
single-source list when evaluating a deployment for use behind their
firewall — keeping it current is a contractual obligation under most DPAs.
