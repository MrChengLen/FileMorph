# Incident Response

This document describes how the FileMorph project responds to a confirmed
security incident — from triage through patch release and post-mortem. It
is the upstream-project process; a self-hoster running their own
deployment will additionally need their own internal IR plan that covers
their data, their users, and their regulatory obligations.

For *reporting* a vulnerability, see
[`SECURITY.md`](../SECURITY.md). This document picks up after a report has
been received and confirmed.

## Severity classification

We classify incidents along the same CVSS-based scale as patches — see
[`patch-policy.md`](./patch-policy.md) for the exact bands. The severity
drives both the patch deadline and the breadth of communication:

| Severity | Initial response | Public disclosure |
|---|---|---|
| Critical | Maintainer paged immediately; all other work paused. | Coordinated; advisory + patch release within 7 days of triage. |
| High | Maintainer paged within one business day. | Advisory + patch release within 30 days of triage. |
| Medium / Low | Tracked in the regular release cycle. | Bundled into the release notes; advisory only if user-action is required. |

## Roles

For an open-source project of FileMorph's current size the roles below
collapse onto the maintainer:

- **Incident Lead** — owns the response, decides on disclosure timing,
  signs off on the fix.
- **Communications** — drafts the advisory, the release notes, and the
  inbound responses to the reporter and to affected operators.
- **Engineering** — produces and reviews the fix, the regression test,
  and the patched release artifacts.

When a Compliance-Edition customer is impacted, that customer's primary
contact is added to the response thread before the advisory goes public.

## Response stages

1. **Receive & acknowledge.** The reporter receives an acknowledgement
   within 72 hours (target: same day). The acknowledgement includes a
   tracking identifier and confirms whether the issue is being handled
   under coordinated disclosure.
2. **Triage.** The Incident Lead reproduces the issue, assigns a CVSS
   score, classifies severity, and decides whether the issue requires a
   coordinated disclosure path (CVE) or whether a regular release with
   notes is sufficient.
3. **Containment.** If the issue is being actively exploited in the
   wild and a fix cannot ship within the patch window, an interim
   mitigation (configuration change, env-var, reverse-proxy rule) is
   published as a workaround in a draft GitHub Security Advisory.
4. **Fix.** The fix lands on `main` with a regression test that fails
   without the patch. The commit message references the GHSA identifier
   when one has been allocated.
5. **Release & disclose.** The patched version is tagged, the Docker
   image is signed and pushed, and the advisory is published. Compliance-
   Edition customers on the security mailing list receive the advisory
   five working days before public disclosure when feasible.
6. **Post-mortem.** Within 30 days of disclosure the maintainer publishes
   a short post-mortem in the project's `runbooks/` (where a runbook
   directory exists) or as a follow-up release note. Format below.

## Post-mortem template

```markdown
# Incident <YYYY-MM-DD> — <one-line summary>

**Severity:** <Critical|High|Medium|Low>
**CVSS:** <vector>
**Identifier:** <GHSA-…> / <CVE-…>
**Affected versions:** <range>
**Patched in:** <vX.Y.Z>

## What happened

<2–4 sentences. What went wrong, who reported it, when it was
discovered, and the user-visible impact. No accusations, no jargon.>

## Why it happened

<Root cause. Refer to the code anchor that introduced the issue and
the anchor that closes it. If the cause was a missing test, say so.>

## What we did

<Triage timeline, the fix, the regression test, the patched release.>

## What we changed

<Process or guard rails that would have caught this earlier — added
test, lint rule, CI check, doc rule, code-owner gate. If the answer is
"nothing", say so and explain why.>

## Acknowledgements

<Reporter (with their consent), reviewers, anyone external who helped
coordinate disclosure.>
```

## Communication

For an active incident, the canonical channel is the GitHub Security
Advisory thread on this repository. Side-channel updates (email,
Compliance-Edition support contacts) are reflected back into the GHSA
thread so there is a single audit trail.

We do not use Slack, Discord, or social media for live incident
coordination. The GitHub Advisory thread is the authoritative timeline.

## What we will not do

- Disclose a vulnerability before a fix is available, except where the
  reporter has chosen to disclose unilaterally and a workaround can be
  published.
- Pay bug bounties (no programme is operated today). Reporters of
  Critical or High severity issues are credited in the advisory unless
  they request anonymity.
- Sue, threaten, or pursue legal action against good-faith researchers
  acting in line with [`SECURITY.md`](../SECURITY.md)'s safe-harbour
  clause.

## See also

- [`SECURITY.md`](../SECURITY.md) — disclosure policy and response-time
  targets.
- [`patch-policy.md`](./patch-policy.md) — release cadence, severity
  scale, signing.
- [`security-overview.md`](./security-overview.md) — the standing
  controls that patches operate on.
