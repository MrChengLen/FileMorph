# Commercial License Agreement — Template

**Status:** Skeleton template — **not a binding contract as it stands.**
**Last reviewed:** 2026-05-12

This document is the starting point for the **Commercial License
Agreement** between a FileMorph Compliance-Edition customer (*Licensee*)
and the FileMorph operator (*Licensor*). It is published in the
open-source repository so a procurement or legal reviewer can read the
substance before requesting a binding contract — it is the agreement
that [`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md) describes, and
it is the "underlying service agreement" referenced by
[`docs/dpa-template.md`](dpa-template.md).

> **Not legal advice.** This template has not been reviewed by counsel.
> Before signing, have it reviewed and tailored by a qualified lawyer in
> your jurisdiction — the statutory references below assume German law in
> a B2B context, and the bracketed `[PLACEHOLDER]` items must be filled
> from the concrete deal. When you are ready to finalise, contact
> `legal@filemorph.io`; a tailored draft, invoice, and activation
> details follow within two business days.

The model this agreement implements — dual-license (AGPL-3.0 +
commercial), server-volume tiers, what the commercial licence does and
does not remove — is in [`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md).
Read that first; this document is the contractual form of it.

---

## 1. Parties

**Licensor:**
- Legal name: Lennart Seidel
- Address: Reetwerder 25b, 21029 Hamburg, Germany
- Contact: `legal@filemorph.io`

**Licensee:**
- Legal name: `[LICENSEE LEGAL NAME]`
- Address: `[LICENSEE ADDRESS]`
- Authorised signatory: `[NAME, ROLE]`

## 2. Definitions

- **"Software"** — FileMorph, the file-conversion / compression
  application published by the Licensor at
  `https://github.com/MrChengLen/FileMorph`, at the version line stated
  in Schedule A, together with its Documentation.
- **"AGPL"** — the GNU Affero General Public License v3.0 under which the
  Software is also published (see `LICENSE` in the repository).
- **"Licensed Scope"** — the deployment scope licensed under this
  Agreement: the tier, number of servers, and employee band stated in
  Schedule A.
- **"Documentation"** — the `docs/` directory of the repository at the
  licensed version line, in particular `security-overview.md`,
  `patch-policy.md`, `sub-processors.md`, `dpa-template.md`,
  `dpa-tom-annex.md`, `support-sla.md`, `onboarding.md`,
  `release-signing.md`, `third-party-licenses.md`.
- **"Support SLA"** — the support commitments per
  [`docs/support-sla.md`](support-sla.md) at the level set in Schedule B.
- **"DPA"** — the Data Processing Agreement per
  [`docs/dpa-template.md`](dpa-template.md) including its Annex II —
  Technical and Organisational Measures per
  [`docs/dpa-tom-annex.md`](dpa-tom-annex.md).
- **"Effective Date"** — the date stated in Schedule A.

## 3. Licence grant

3.1 Subject to payment of the Fees and compliance with this Agreement,
the Licensor grants the Licensee, for the Term and within the Licensed
Scope, a **non-exclusive, non-transferable, non-sublicensable** (except
under §4) right to install, use, and modify the Software, including the
right to run it as a network-accessible service and to embed it in the
Licensee's own systems, **without the source-disclosure obligations of
AGPL §§4–6 and §13 ("Remote Network Interaction")** for the Licensed
Scope.

3.2 Outside the Licensed Scope — additional servers, more employees than
the band in Schedule A, or use by a different legal entity — AGPL-3.0
governs unless and until the Licensed Scope is extended by a written
amendment (a "true-up", typically a move to a higher tier per
[`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md)).

3.3 This Agreement does not remove AGPL-3.0 from the public repository
and does not affect any other party's rights under AGPL-3.0. The
Licensee may not redistribute a build received under this Agreement as
AGPL-licensed or open-source.

## 4. OEM / white-label (applies only if Schedule A specifies the OEM tier)

If Schedule A specifies the OEM / white-label tier, §3.1 additionally
includes the right to redistribute the Software (in source or binary
form) as an integrated component of the Licensee's own product to the
Licensee's customers, and to grant those customers a sublicence limited
to use of the Software as part of that product, provided that: (a) the
attribution required by §11.3 is preserved; (b) the Licensee's customers
receive no greater rights than the Licensee holds; and (c) the
redistribution terms are agreed in Schedule A.

## 5. Restrictions

The Licensee shall: (a) preserve the copyright notices and
`SPDX-License-Identifier` headers in the Software's source files; (b)
comply with the licences of the third-party components bundled with the
Software (see [`docs/third-party-licenses.md`](third-party-licenses.md))
and preserve their notices; (c) not represent a build received under
this Agreement as being licensed under AGPL-3.0 or another open-source
licence; (d) not use the Software outside the Licensed Scope; (e) not
remove or circumvent the audit-log integrity mechanism where the
Licensee relies on it for the Licensee's own compliance.

## 6. Fees and payment

6.1 The Licensee shall pay the annual Fees stated in Schedule A,
invoiced annually in advance, due within thirty (30) days of the invoice
date.

6.2 Fees are exclusive of VAT. For cross-border supplies within the EU
to a VAT-registered business, the reverse-charge mechanism applies and
the Licensee provides a valid VAT-ID.

6.3 Overdue amounts bear interest at the statutory rate (§288 BGB) from
the due date.

6.4 Fees for a renewal Term may be adjusted by the Licensor on written
notice given at least ninety (90) days before the end of the
then-current Term; the Licensee may decline the renewal under §7.

## 7. Term and renewal

7.1 The initial Term is twelve (12) months from the Effective Date.

7.2 The Term renews automatically for successive twelve (12) month
periods unless either party gives written notice of non-renewal at least
ninety (90) days before the end of the then-current Term.

7.3 Either party may terminate this Agreement for the other party's
material breach that remains uncured thirty (30) days after written
notice of the breach.

## 8. Support and security maintenance

8.1 The Licensor provides support per the Support SLA (Schedule B and
[`docs/support-sla.md`](support-sla.md)).

8.2 Independently of the Support SLA, the Licensor follows the
vulnerability-disclosure and patch timelines in `SECURITY.md` and
[`docs/patch-policy.md`](patch-policy.md) for all users of the Software;
a paid Support SLA provides priority handling, not a shortened patch
clock.

## 9. Onboarding

The Licensor provides onboarding at the level corresponding to the
Licensed Scope tier, per [`docs/onboarding.md`](onboarding.md) and
Schedule D. Onboarding is enablement and paperwork for a self-hosted
deployment; it is not managed hosting.

## 10. Data protection

The parties enter into the DPA (Schedule C, incorporating
[`docs/dpa-template.md`](dpa-template.md) and its Annex II per
[`docs/dpa-tom-annex.md`](dpa-tom-annex.md)), finalised during
onboarding. This Agreement is the "underlying service agreement"
referenced by the DPA. In case of conflict between this Agreement and
the DPA on a data-protection matter, the DPA prevails.

## 11. Intellectual property and attribution

11.1 The Software is licensed, not sold. The Licensor and the FileMorph
contributors retain all intellectual-property rights in the Software.

11.2 No rights are granted to the Licensee other than those expressly
stated in this Agreement.

11.3 The Licensee shall preserve attribution to FileMorph and its
contributors in the Software's source files and shall not present the
Software as the Licensee's own original work.

## 12. Warranties and disclaimer

12.1 The Licensor warrants that it has the right to grant the licence in
§3 and, where Schedule A specifies the OEM tier, §4.

12.2 Otherwise the Software is provided **"as is"**. The Licensor does
not warrant that the Software is free of defects or fit for a particular
purpose beyond the functionality described in the Documentation. To the
extent permitted by law, all other warranties are excluded.

12.3 For a material defect in functionality described in the
Documentation, the Licensee's remedy is: (a) a corrected release within
the timelines in [`docs/patch-policy.md`](patch-policy.md) according to
severity, or (b) if the Licensor does not provide a correction within a
reasonable cure period, a pro-rata refund of pre-paid Fees for the
remainder of the then-current Term.

12.4 Statutory rights that cannot be excluded or limited by agreement
(in particular under §§309 No. 8, 444, 639 BGB and the
Produkthaftungsgesetz) remain unaffected.

## 13. Liability

13.1 The Licensor is liable without limitation for: damages from injury
to life, body, or health; damages caused by intent or gross negligence;
liability under the Produkthaftungsgesetz; fraudulent concealment of a
defect; and breach of an express guarantee.

13.2 For the breach of a material contractual obligation (a
"Kardinalpflicht" — an obligation whose fulfilment is essential to the
proper performance of this Agreement and on which the Licensee may
ordinarily rely) caused by ordinary negligence, the Licensor's liability
is limited to the typical, foreseeable damage.

13.3 In all other cases, liability for ordinary negligence is excluded.

13.4 Subject to §13.1, the Licensor's aggregate liability under or in
connection with this Agreement for any twelve (12) month period is
limited to the Fees paid by the Licensee for that period.

13.5 Liability for the processing of personal data under Article 82 GDPR
is allocated as set out in the DPA and is limited by this §13 only to
the extent Article 82 permits.

## 14. Third-party intellectual-property claims

14.1 If a third party asserts that the Software as delivered by the
Licensor infringes that party's intellectual-property rights, the
Licensor will, at its option and expense, either (a) procure for the
Licensee the right to continue using the Software, (b) modify or replace
the affected part so it is non-infringing while substantially equivalent
in function, or (c) terminate the licence to the affected part and
refund the pro-rata pre-paid Fees for the remainder of the then-current
Term.

14.2 §14.1 does not apply to claims arising from: the Licensee's
modifications to the Software; combination of the Software with software
or data not supplied by the Licensor where the claim would not have
arisen from the Software alone; or use outside the Licensed Scope.

14.3 The Licensor's obligations under §14.1 are subject to the liability
cap in §13.4 and are the Licensee's sole remedy for third-party
intellectual-property claims.

## 15. Confidentiality

15.1 Each party shall keep confidential the other party's non-public
information disclosed in connection with this Agreement (including the
filled-in Schedules, fees, and the Licensee's deployment details) and
use it only for performing this Agreement.

15.2 §15.1 does not apply to information that is or becomes public
through no fault of the receiving party, was lawfully known before
disclosure, is independently developed without use of the disclosing
party's information, or must be disclosed by law or court order (with
prior notice to the other party where lawful).

15.3 The Software itself is published under AGPL-3.0 and is not
confidential.

15.4 This §15 survives termination for three (3) years.

## 16. Effect of termination

16.1 On termination or expiry of this Agreement, the licence in §3 (and
§4, if applicable) ends. The Licensee's continued use of the Software is
thereafter governed by AGPL-3.0.

16.2 Existing installations may continue to run; the Licensor does not
disable or force-update deployed instances. Continued updates after
termination require a current commercial licence or compliance with
AGPL-3.0; the Documentation as a contractual deliverable, the Support
SLA, and onboarding cease.

16.3 No Fees are refunded on termination except as expressly provided in
§§12.3, 14.1.

## 17. General

17.1 Neither party may assign this Agreement without the other's prior
written consent, except to a successor in a merger, acquisition, or sale
of substantially all assets, on written notice.

17.2 This Agreement, together with its Schedules and the Documentation
referenced in it as in effect on the Effective Date, is the entire
agreement between the parties on its subject matter and supersedes prior
discussions.

17.3 Amendments must be in writing and signed by both parties.

17.4 If a provision is or becomes invalid, the remainder stays in
effect and the parties replace the invalid provision with a valid one
closest to its economic intent.

17.5 Failure to enforce a provision is not a waiver of it.

17.6 Neither party is liable for failure or delay caused by events
beyond its reasonable control, for the duration of the event.

17.7 Notices are in writing; email to the addresses in §1 is sufficient,
with confirmation of receipt for notices of breach or termination.

## 18. Governing law and jurisdiction

This Agreement is governed by the laws of the Federal Republic of
Germany, excluding the UN Convention on Contracts for the International
Sale of Goods (CISG). The exclusive place of jurisdiction is Hamburg,
Germany, to the extent permitted by law.

---

## Schedule A — Licensed Scope and Fees

| Item | Value |
|---|---|
| Tier | `[Starter / Standard / Enterprise / KRITIS–air-gap / OEM]` |
| Number of servers licensed | `[N]` |
| Employee band | `[≤ 50 / ≤ 2 000 / unlimited / as agreed]` |
| Annual Fee (excl. VAT) | `[€ … — per COMMERCIAL-LICENSE.md, or as negotiated for Enterprise / KRITIS / OEM]` |
| Multi-year discount, if any | `[…]` |
| OEM redistribution terms (OEM tier only) | `[…]` |
| Licensed version line | `[e.g. v1.x — see docs/patch-policy.md]` |
| Effective Date | `[YYYY-MM-DD]` |

## Schedule B — Support SLA terms

Incorporates [`docs/support-sla.md`](support-sla.md). Tier-specific terms
filled at finalisation:

| Item | Value |
|---|---|
| Severity response windows (P1 / P2 / P3 / P4) | `[per the tier — see docs/support-sla.md]` |
| Coverage hours | `[business hours Europe/Berlin / extended / 24×7 — as agreed]` |
| Named support contact | `[…]` |
| Escalation path | `[…]` |
| Backport line (Enterprise / KRITIS) | `[version line + offline-update tooling, if applicable]` |

## Schedule C — Data Protection

Incorporates [`docs/dpa-template.md`](dpa-template.md) and its Annex II —
Technical and Organisational Measures per
[`docs/dpa-tom-annex.md`](dpa-tom-annex.md), with the bracketed
placeholders in those documents filled in for this deployment during
onboarding. The DPA is counter-signed together with this Agreement or at
the latest before go-live.

## Schedule D — Onboarding scope

Per [`docs/onboarding.md`](onboarding.md) at the tier stated in Schedule
A. Any agreed à-la-carte additions: `[…]`.

---

## How to finalise

1. Read [`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md) for the model
   and the published tier fees.
2. Fill Schedules A–D from the concrete deal.
3. **Have the draft reviewed and tailored by a qualified lawyer** — the
   liability, warranty, and indemnity clauses (§§12–14) in particular
   must match your jurisdiction and risk appetite; the German statutory
   references above are illustrative, not authoritative.
4. Both parties counter-sign (printed PDF or qualified electronic
   signature); the DPA (Schedule C) is counter-signed alongside or
   before go-live.
5. Send the completed draft to `legal@filemorph.io`. Turnaround is
   typically two business days.

## See also

- [`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md) — the model, the
  tiers, and the published fees this Agreement implements.
- [`docs/dpa-template.md`](dpa-template.md) + [`docs/dpa-tom-annex.md`](dpa-tom-annex.md)
  — Schedule C.
- [`docs/support-sla.md`](support-sla.md) — Schedule B.
- [`docs/onboarding.md`](onboarding.md) — Schedule D.
- [`docs/patch-policy.md`](patch-policy.md) · [`docs/third-party-licenses.md`](third-party-licenses.md)
  · [`SECURITY.md`](../SECURITY.md) — referenced in §§5, 8, 12.
