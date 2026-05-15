# Patch & Release Policy

This document explains how FileMorph releases work, how long each release
is supported, and how security patches are issued. It is written for
self-hosters who need to know how often they need to redeploy, and for
procurement reviewers who need to assess whether the upstream cadence is
compatible with their patch-management requirements.

## Release line

FileMorph uses a single `main` branch. Each merge to `main` that ships a
user-visible change is tagged `vX.Y.Z` and built into a Docker image
published to GitHub Container Registry under
`ghcr.io/mrchenglen/filemorph`.

There is no long-term-support branch. Self-hosters track the latest
`main` tag, or pin to a specific `vX.Y.Z` and upgrade on their own
schedule. Pinning to a major version (e.g. `v1`) is supported and
follows the SemVer guarantee below.

## Versioning

We follow [Semantic Versioning 2.0](https://semver.org/):

| Component | Bumped when |
|---|---|
| `MAJOR` | Backwards-incompatible API change, removed env-var, removed converter format, breaking schema migration without an automatic upgrade path. |
| `MINOR` | New format, new endpoint, new env-var, new optional feature. |
| `PATCH` | Bug fix, dependency update, security patch, documentation. |

A `MAJOR` bump is preceded by at least one `MINOR` release that
deprecates the removed surface and emits a deprecation warning.

## Patch severity and timeline

We classify security issues using the same scale that
[GitHub Security Advisories](https://docs.github.com/en/code-security/security-advisories)
uses (CVSS v3.x base score). The patch-release timelines below apply
*after* the issue has been triaged and confirmed:

| Severity | CVSS range | Patch released within |
|---|---|---|
| Critical | 9.0 – 10.0 | 7 days |
| High | 7.0 – 8.9 | 30 days |
| Medium | 4.0 – 6.9 | next regular release |
| Low | 0.1 – 3.9 | next regular release |

A *regular release* is the next planned `MINOR` or `PATCH` cut, which
historically lands every 1–4 weeks.

For deployments behind an air-gap or with a fixed change-window, we
publish patch-only branches on request — contact `security@filemorph.io`
with the version you need a backport for.

## Dependency hygiene

`pip-audit -r requirements.txt` runs on every CI build and blocks the
merge on any High or Critical finding. Lower-severity findings are
batched into the next regular release.

We pin direct dependencies in `requirements.txt` to a specific minor
version and re-evaluate at each release. Indirect dependencies are
pinned via `requirements.lock` (when present); deployments that need
deterministic builds should `pip install -r requirements.lock`.

The full dependency manifest is available as a
[CycloneDX SBOM](https://cyclonedx.org/) attached to each GitHub
release as `filemorph-{version}.cdx.json`. Use it for vulnerability
scanning against your existing CVE pipeline.

## Release announcements

| Channel | Content |
|---|---|
| GitHub Releases | Tag, changelog, SBOM attachment, signed Docker image digest. |
| GitHub Security Advisories | Security-related releases (Critical and High). |
| `security@filemorph.io` mailing-list | Notified for Critical and High before public disclosure (paid Compliance-Edition customers, on request). |

## Signing & verification

Each released Docker image is signed with [cosign](https://github.com/sigstore/cosign)
using GitHub's OIDC keyless flow. To verify before pulling:

```bash
cosign verify ghcr.io/mrchenglen/filemorph:vX.Y.Z \
  --certificate-identity-regexp '^https://github\.com/MrChengLen/FileMorph/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

Git tags are signed with the maintainer's GPG key listed in
[`docs/release-signing.md`](./release-signing.md). The release
workflow refuses to publish a release whose tag does not verify
against an imported maintainer key, so an unsigned or tampered tag
never produces a release artefact. Manual check on a cloned
repository:

```bash
awk '/-----BEGIN PGP PUBLIC KEY BLOCK-----/,/-----END PGP PUBLIC KEY BLOCK-----/' \
    docs/release-signing.md \
  | gpg --import
git verify-tag vX.Y.Z
```

## End-of-life

A release line stops receiving patches when the next `MAJOR` is published
plus 90 days. The transition window is announced in the release notes of
the new `MAJOR` along with the migration guide.

## How a self-hoster keeps current

Recommended cadence:

1. Pin to a `vX.Y` tag (e.g. `v1.0`).
2. Subscribe to GitHub Releases on this repository (the *Watch → Custom →
   Releases* setting).
3. Schedule a redeploy after every PATCH or MINOR release, or at minimum
   monthly.
4. Subscribe to GitHub Security Advisories on this repository to be
   notified of Critical and High issues out-of-band from the regular
   release cycle.

For deployments where each upgrade requires an internal change-window,
the SBOM and signed image attestations let your security team
pre-evaluate a release before it hits production.

## See also

- [`SECURITY.md`](../SECURITY.md) — vulnerability disclosure policy.
- [`support-sla.md`](./support-sla.md) — the Compliance Edition support
  framework (set per agreement) and the security-fix timeline (all users), kept
  distinct.
- [`incident-response.md`](./incident-response.md) — what happens after a
  vulnerability is confirmed.
- [`security-overview.md`](./security-overview.md) — the controls each
  patch is operating against.
