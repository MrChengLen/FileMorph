# Onboarding (Compliance Edition)

This document defines what *onboarding* means once a Compliance-Edition
licence is signed — what each tier includes, the sequence, the
timeframe, and what is out of scope. It is published in the open-source
repository so a prospect or procurement reviewer can see, before
signing, what the "dedicated onboarding" line in
[`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md) actually buys.

> **FileMorph is self-hosted.** Onboarding is *enablement and
> paperwork* — getting your team to a verified, production-ready
> deployment with the support relationship and the Article 28
> documentation in place. It is **not** managed hosting: you run the
> instance on your own (or your provider's) infrastructure; we do not
> operate it for you. A managed-hosting option does not exist today; if
> it ever does, it will be a separate product, not part of onboarding.

## What each tier's onboarding includes

| | **Starter** | **Standard** | **Enterprise** | **KRITIS / air-gap** |
|---|:---:|:---:|:---:|:---:|
| Documentation pack (DPA template, TOM annex, sub-processor list, security overview, patch policy, third-party-licenses, SBOM how-to) | ✔ | ✔ | ✔ | ✔ |
| Email Q&A round on deployment + licence scope | ✔ | ✔ | ✔ | ✔ |
| Kickoff call (scope, timeline, named contacts) | — | ✔ | ✔ | ✔ |
| Deployment-architecture review (your topology: reverse proxy, DB, network, env vars) | — | ✔ | ✔ | ✔ |
| DPA + "Annex II — TOM" finalised in the pilot conversation (placeholders filled for your deployment) | — | ✔ | ✔ | ✔ |
| Your security questionnaire answered (SIG-Lite / VSA / in-house form) | — | ✔ | ✔ | ✔ |
| Artifact-verification walkthrough (`cosign verify`, SBOM ingestion, audit-log `verify_chain`, veraPDF check) | — | ✔ | ✔ | ✔ |
| Dedicated onboarding contact + named escalation path | — | — | ✔ | ✔ |
| Deployment-readiness checklist tailored to your environment | — | — | ✔ | ✔ |
| Support-SLA + escalation-path setup (per [`support-sla.md`](support-sla.md)) | — | — | ✔ | ✔ |
| Post-go-live check-ins (~first 30 days) | — | — | ✔ | ✔ |
| Offline-update / air-gap tooling walkthrough; reproducible-build status review; external pen-test-report exchange | — | — | — | ✔ |

`✔` = included; `—` = not at that tier (a single item can be bought à la
carte at a lower tier — ask during the pilot call). The KRITIS / air-gap
column is *on top of* everything in the Enterprise column.

## The onboarding sequence

A typical engagement, contract-signed to go-live:

1. **Kickoff & scope** *(Standard+)* — a call: confirm the deployment
   target, the data categories, the named contacts on both sides, the
   timeline. Output: the onboarding plan.
2. **Deployment-architecture review** *(Standard+)* — walk through your
   intended topology — which reverse proxy, where Postgres lives,
   network segmentation, `CORS_ORIGINS` / env-var settings, the
   "Operational Hardening" checklist in
   [`security-overview.md`](security-overview.md). You get back any
   deployment-specific notes.
3. **Compliance paperwork finalised** *(Standard+)* — the
   [DPA template](dpa-template.md) and its
   [Annex II — TOM](dpa-tom-annex.md) are filled in for your concrete
   deployment (instance location, network segmentation, on-call,
   pen-test status, retention values) and counter-signed; the
   [sub-processor list](sub-processors.md) is confirmed, or reduced in
   scope if you operate fully self-contained.
4. **Security due-diligence support** *(Standard+)* — your security
   questionnaire is answered from the existing documentation
   ([`threat-model.md`](threat-model.md), [`security-overview.md`](security-overview.md),
   [`patch-policy.md`](patch-policy.md), [`third-party-licenses.md`](third-party-licenses.md),
   [`release-signing.md`](release-signing.md)); we walk your team
   through verifying the release artifacts themselves — `cosign verify`,
   the CycloneDX SBOM, the audit-log hash chain (`verify_chain`), the
   veraPDF conformance gate.
5. **Deployment-readiness check** *(Enterprise+)* — a written checklist
   tailored to your environment: TLS termination, trusted-proxy config,
   `JWT_SECRET` strength, backup regime, monitoring, and the
   "Operational Hardening" items in
   [`security-overview.md`](security-overview.md).
6. **Go-live & handover to support** — the deployment goes to
   production; the [support relationship](support-sla.md) becomes active
   (named contact + escalation path for Enterprise / KRITIS); the
   security-advisory pre-notification list is set up if you want
   advance notice of Critical / High issues.
7. **Post-go-live check-ins** *(Enterprise+)* — light-touch check-ins
   over roughly the first 30 days to catch anything that surfaces under
   real load; then the relationship is steady-state on the support SLA.

For **air-gap / KRITIS** deployments, add: a walkthrough of the
offline-update tooling, a review of reproducible-build status (a Year-2
roadmap item — see [`release-signing.md`](release-signing.md) § Out of
scope), and the exchange of the external pen-test report once it is on
file (the KRITIS variant is not generally quoted before then — see
[`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md)).

## Timeframe

Contract-signed to go-live is typically **2–6 weeks**, almost entirely
gated by *your* internal processes (security review sign-off, change
windows, procurement counter-signature) rather than ours — the
documentation pack and templates are off-the-shelf, and the
finalisation / review calls are scheduled within a few business days.
KRITIS / air-gap engagements run longer because of the pen-test exchange
and the offline-tooling setup.

## What onboarding does *not* include

- **Operating your deployment** — it is self-hosted; you run it. We do
  not manage your infrastructure, scale it, or hold pager duty for it.
- **Writing your integration code** — embedding FileMorph in a citizen
  portal, a closed-source wrapper, or any bespoke glue is your work (the
  OEM tier covers redistribution *rights*, not development); we advise,
  we do not build it.
- **Migrating existing data into FileMorph** — conversions are
  stateless; there is nothing to migrate beyond pointing the audit log
  at your Postgres, if you use it.
- **Third-party-service setup** — your Hetzner / Stripe / Zoho /
  Cloudflare accounts and their configuration are yours; see
  [`sub-processors.md`](sub-processors.md).
- **24×7 coverage during onboarding** — onboarding runs in business
  hours; the SLA (including any contracted extended-hours coverage)
  takes effect at go-live, per [`support-sla.md`](support-sla.md).
- **Training beyond the artifact-verification walkthrough** — deeper
  hands-on training for your team is a separate engagement; ask during
  the pilot call.

## See also

- [`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md) — the Compliance
  Edition tiers and what each includes.
- [`support-sla.md`](support-sla.md) — what onboarding hands off to.
- [`dpa-template.md`](dpa-template.md) + [`dpa-tom-annex.md`](dpa-tom-annex.md)
  — the paperwork finalised during onboarding.
- [`security-overview.md`](security-overview.md) · [`threat-model.md`](threat-model.md)
  · [`patch-policy.md`](patch-policy.md) · [`sub-processors.md`](sub-processors.md)
  · [`third-party-licenses.md`](third-party-licenses.md) · [`release-signing.md`](release-signing.md)
  — the artifacts verified during onboarding.
