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
| **Hetzner Online GmbH** | Server hosting | Whatever the server holds: uploads while they are processed, the database if configured (accounts, usage records, audit log), and the logs — access logs with client IPs are written by the reverse proxy and by the application's uvicorn server. | Data centre in the EU. | Inherent to the deployment; switch hosting provider to opt out. |
| **Cloudflare Inc.** | DNS, DDoS protection, edge caching | All traffic to the service: the edge terminates TLS, so it handles request metadata (client IP, URL, headers) and, in transit, request and response bodies — uploaded and converted files included. FileMorph uses no Cloudflare storage. | Distributed (operator may set a regional preference). | Optional; remove the proxy and serve the origin directly. |
| **Stripe Inc.** | Payment processing (Cloud Edition only) | Customer email and an internal user identifier; card data is collected by Stripe directly and never reaches FileMorph. | United States (EU SCCs apply via Stripe DPA). | Disabled when `STRIPE_SECRET_KEY` is empty. |
| **Zoho Corporation B.V.** | Transactional email (email verification, password reset, payment-failure notices, account-deletion confirmation) and delivery of contact-form messages to the operator | Recipient address and the email body (e.g. a reset link); for a contact-form message, the sender's name, email address, subject and message. | EU data centres in Amsterdam (NL) and Dublin (IE). | Disabled when `SMTP_HOST` is empty. |
| **GitHub Inc.** | Source distribution and issue tracking | Public repository metadata only; not in the request path of any deployment. | United States. | Inherent to the open-source distribution model. |

## What FileMorph itself does NOT send out

The FileMorph application code, by design, never transmits user-uploaded
files, file contents, or filenames to any sub-processor. The only outbound
calls in the application code are:

- PostgreSQL queries to the configured database (Cloud Edition).
- SMTP submissions to the configured relay: account and billing emails
  (Cloud Edition), and contact-form messages and cancellations that need
  manual handling to the operator.
- Stripe API calls — creating the customer and the Checkout and
  Billing-Portal sessions, setting a subscription to end when its holder
  cancels online, cancelling subscriptions when an account is deleted —
  and responses to Stripe's signed webhooks (Cloud Edition, paid tiers).

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
