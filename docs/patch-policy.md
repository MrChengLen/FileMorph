# Patch & Release Policy

This document explains how FileMorph releases work, how long each release
is supported, and how security patches are issued. It is written for
self-hosters who need to know how often they need to redeploy, and for
procurement reviewers who need to assess whether the upstream cadence is
compatible with their patch-management requirements.

## Release line

FileMorph uses a single `main` branch. **Every merge to `main`** builds
and pushes the `latest` (slim) and `office` Docker images, plus a
`sha-<short-commit>` tag for each — this is the continuous path, and how
most fixes reach a self-hoster: pull `latest` / `office` again.
Separately, at the maintainer's discretion, a commit on `main` gets a
GPG-signed git tag `vX.Y.Z`; that tag build additionally pushes the
image tags `X.Y.Z` and `X.Y` — **no `v` prefix on the image tag, and no
bare-major tag** (pin `X.Y.Z` or `X.Y`, never just `X`). As of this
writing there has been one such tagged release, `v1.1.0` (2026-06-01) —
see [GitHub Releases](https://github.com/MrChengLen/FileMorph/releases)
for the current list.

There is no long-term-support branch. Self-hosters either track `latest`
/ `office` for continuous fixes with no version pinning, or pin to a
specific `X.Y.Z` / `X.Y` image tag and upgrade deliberately on their own
schedule.

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

A *regular release* is the next tagged `vX.Y.Z` cut, made at the
maintainer's discretion rather than on a fixed cadence — see "Release
line" above. Independently of tagged releases, a merged fix reaches the
continuously built `latest` / `sha-*` images as soon as it lands on
`main`.

For deployments behind an air-gap or with a fixed change-window, we
publish patch-only branches on request — contact `security@filemorph.io`
with the version you need a backport for.

## Dependency hygiene

`pip-audit -r requirements.lock` runs on every CI build and blocks the
merge on any finding that is not explicitly ignored — an
`--ignore-vuln` entry in `ci.yml` with a documented reason. How fast
the fix ships follows the severity table above. The lockfile is audited
rather than the manifest because the lockfile is what the image
installs.

`requirements.txt` states minimum versions for direct dependencies and
is the file Dependabot updates. `requirements.lock`, compiled from it
with `uv pip compile --generate-hashes`, resolved for the image's Python
version and platform, pins
every direct *and* transitive dependency to an exact version plus hash — and it is what
the Docker image installs, via `pip install --require-hashes`. Two
builds of the same commit therefore install byte-identical
dependencies, and a re-uploaded or tampered wheel fails the hash
check. CI fails if the two files drift apart or if the lockfile was
compiled on a different Python version than the image ships.

The full Python dependency manifest is available as a
[CycloneDX SBOM](https://cyclonedx.org/) attached to each GitHub
release as `filemorph-{version}.cdx.json`. It is generated from a
clean environment installed from `requirements.lock` exactly the way
the image installs it, so it lists the application's Python
dependencies at the versions the image ships. System packages from
the base image and `apt` (FFmpeg, Ghostscript, LibreOffice) are not
in it. Use it for vulnerability scanning against your existing CVE
pipeline.

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

1. Pin to a specific image tag (`X.Y.Z` or `X.Y`, e.g. `1.1.0`) for
   controlled, deliberate upgrades — or track `latest` / `office` if you
   want fixes as soon as they merge to `main`.
2. Subscribe to GitHub Releases on this repository (the *Watch → Custom →
   Releases* setting) to hear about tagged `vX.Y.Z` cuts.
3. If pinned to a version tag, redeploy when a new one ships. If tracking
   `latest`, re-pull periodically — otherwise fixes that already merged
   never reach your instance.
4. Subscribe to GitHub Security Advisories on this repository to be
   notified of Critical and High issues out-of-band from tagged
   releases.

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
