# FileMorph — Commercial License

> Behörden, Krankenhäuser und Kanzleien finden eine deutschsprachige
> Erläuterung der Lizenz-Abgrenzung in
> [`docs/agpl-fuer-behoerden.md`](docs/agpl-fuer-behoerden.md). Das
> Compliance-Edition-Datenblatt mit Trust-Artefakten (Threat-Model,
> SBOM-Pipeline, Patch-Policy) liegt unter
> [`/enterprise`](https://filemorph.io/enterprise) auf der SaaS-Site.

FileMorph is distributed under a **dual-license model**:

| Use case | License | Cost |
|---|---|---|
| Personal use, academic use, open-source projects | **AGPL-3.0** (see [`LICENSE`](LICENSE)) | Free |
| Self-hosting inside a company for internal use | **AGPL-3.0** (see [`LICENSE`](LICENSE)) | Free |
| Embedding FileMorph in a **closed-source** commercial product, **SaaS**, or service without publishing your modifications | **Commercial License** (this file) | Paid |

---

## Why a commercial license?

AGPL-3.0 requires anyone who runs a modified version of FileMorph **as a
publicly-accessible network service** to publish the complete corresponding
source code of the modified version to its users. For many commercial
deployments — white-labelled SaaS products, embedded file-conversion inside
a closed-source customer portal, OEM distribution — that obligation is
incompatible with the business model.

The Commercial License removes the AGPL copyleft obligation. You receive
the right to use, modify, and redistribute FileMorph as part of a proprietary
product without disclosing your changes.

---

## What a Commercial License includes

- Exemption from AGPL-3.0 copyleft (Sections 13 "Remote Network Interaction" in particular)
- Right to integrate FileMorph source or binaries into a proprietary product
- Right to offer FileMorph-as-a-Service without publishing modifications
- Priority response on security advisories
- Support SLA per the commercial agreement — response windows, coverage hours, and escalation are set individually; see [`docs/support-sla.md`](docs/support-sla.md) for the framework (severity model, what an agreement covers)

## What a Commercial License does *not* remove

- Copyright attribution to FileMorph contributors must be preserved in source files
- Third-party open-source components keep their own licenses — see [`docs/third-party-licenses.md`](docs/third-party-licenses.md) (all permissive or MPL-2.0; the commercial licence does not, and need not, relicense them; two native-layer caveats are noted there for anyone redistributing the Docker image)
- Warranty disclaimer and liability limitation apply as in any commercial software contract
- You may not redistribute the commercial-licensed build as AGPL or open source

---

## Pricing (indicative — final terms per contract)

The commercial-license offer is structured as a **Compliance Edition** with
volume-based tiers. Procurement-driven buyers (Behörden, Krankenhäuser,
Kanzleien, KRITIS-Operatoren) typically take Standard or Enterprise; small
agencies and dev-shops embedding FileMorph into their own tooling take
Starter. Pricing is **server-volume-based, not per-seat** — large
organisations (e.g. a 5.000-Mitarbeitende Behörde) do not pay seat-multiples
for a back-end file-conversion service.

| Tier | Scope | Annual |
|---|---|---|
| **Compliance Starter** | 1 server, ≤ 50 staff | € 1.490 |
| **Compliance Standard** | 3 servers, ≤ 2.000 staff | € 7.490 |
| **Compliance Enterprise** | unlimited servers, dedicated onboarding, custom SLA | from € 24.900 |
| **OEM / white-label** | Embed + redistribute inside your own product | Case-by-case |

What "dedicated onboarding" (and the lighter onboarding at the other
tiers) includes — kickoff call, deployment-architecture review, DPA +
"Annex II — TOM" finalisation, security-questionnaire answers, and a
tailored deployment-readiness checklist plus post-go-live check-ins at
the Enterprise tier — is defined in [`docs/onboarding.md`](docs/onboarding.md).

KRITIS- and air-gap-deployment variants are negotiated case-by-case and
include offline-update tooling, dedicated 4-hour reaction-time SLA, and
patch-backports onto a fixed version line. These tiers are not generally
quoted before an external pen-test report is on file — see
[`docs/patch-policy.md`](docs/patch-policy.md) for the release-line and
patching cadence, and [`docs/support-sla.md`](docs/support-sla.md) for the
support framework (the SLA itself is set per agreement, not published).

> Note: the SaaS plans on [filemorph.io/pricing](https://filemorph.io/pricing) (Pro / Business)
> are a separate offering — usage of the hosted API. The tiers above license the
> *source code* for self-hosted closed-source, compliance, and OEM use.

Prices exclude VAT. Multi-year discounts available.

---

## How to obtain a commercial license

Send an email with your intended use case, company name, and expected
deployment scope to:

**licensing@filemorph.io**

A commercial agreement, invoice, and activation details are provided within
two business days. The signature-ready agreement template — the structure of
that "commercial agreement", with the Schedules filled in per deal — is
[`docs/commercial-license-agreement-template.md`](docs/commercial-license-agreement-template.md),
published for procurement review (have it reviewed by counsel before signing).

---

## Contributions

Contributions to the FileMorph open-source project are accepted under
the AGPL-3.0 terms in [`LICENSE`](LICENSE). By submitting a pull request
you agree that FileMorph maintainers may additionally distribute your
contribution under the Commercial License described above. See
[`CONTRIBUTING.md`](CONTRIBUTING.md) for details.

---

*Copyright © 2026 Lennart Seidel / FileMorph. All rights reserved.*
