# Release signing

FileMorph publishes two cryptographic claims for every tagged release:

1. **The git tag is GPG-signed** by a maintainer key listed in this
   document. The release workflow refuses to publish a release whose
   tag does not verify against an imported public key here.
2. **The container image is cosign-signed** via Sigstore keyless OIDC.
   See [`docker.yml`](../.github/workflows/docker.yml) and the
   `IMAGE_DIGEST.txt` attestation attached to each GitHub release.

Both claims are independent: a forged tag would fail (1); a forged
image at the published digest would fail (2). A consumer who needs
end-to-end provenance verifies both.

The images also carry a signed **SBOM attestation** listing the Python
packages they ship. [Verifying the SBOM
attestation](#verifying-the-sbom-attestation) says what it covers and
how to check it.

## Why this matters for the Compliance edition

EVB-IT contracts (March 2026 update) require the procurer to be able
to verify that the artefact they install is the one the upstream
project published. Container-only signing is not enough — a forged
git tag could deceive someone building from source. Source-only
signing is not enough — the published image must be tied to a
verifiable identity. This document plus the cosign workflow cover
both surfaces.

ISO 27001 A.14.2.4 ("System acceptance testing") and BSI APP.5.1
("Container") both expect the signing claims to be reproducible
*outside* the repository — i.e. a third-party auditor can verify
without our help. Sigstore's transparency log (Rekor) and the public
PGP keys below satisfy that expectation.

## Verifying a release tag

```bash
# 1. Clone the repo (no special permissions needed)
git clone https://github.com/MrChengLen/FileMorph
cd FileMorph

# 2. Import the maintainer public keys from this file
awk '/-----BEGIN PGP PUBLIC KEY BLOCK-----/,/-----END PGP PUBLIC KEY BLOCK-----/' \
    docs/release-signing.md \
  | gpg --import

# 3. Verify the tag — exit 0 means the signature matches one of the
#    imported keys; non-zero means do not trust the artefact.
git verify-tag v1.2.3
```

## Verifying the container image

```bash
# Pull-by-tag is fine; cosign resolves to the digest internally.
cosign verify ghcr.io/mrchenglen/filemorph:1.2.3 \
  --certificate-identity-regexp '^https://github\.com/MrChengLen/FileMorph/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

A successful verification prints the signing certificate (issuer
`https://token.actions.githubusercontent.com`, subject
`https://github.com/MrChengLen/FileMorph/.github/workflows/docker.yml@refs/tags/...`),
plus a Rekor transparency-log inclusion proof.

## Verifying the SBOM attestation

[`docker.yml`](../.github/workflows/docker.yml) attests the CycloneDX
SBOM to every image it pushes: the slim and the office image, for each
release tag and each build of `main`. The attestation binds the SBOM to
the image digest and is signed through Sigstore keyless OIDC, like the
image. It is stored with the repository's attestations and pushed to
GHCR next to the image. Images built before this was introduced, v1.1.0
among them, have none: `gh` then finds no attestation to verify.

**What the SBOM covers:** the Python packages the image installs from
`requirements.lock`, at the locked versions, plus the `pip` of the
virtualenv it is generated from, whose version can differ from the
image's. It is generated from a clean install of the lockfile, not by
scanning the image, so it does not list the Python interpreter, the
Debian packages of the `python:3.14-slim` base image, or those the
Dockerfile adds with `apt` (FFmpeg, Ghostscript, the Cairo/Pango stack,
LibreOffice in the office image). Scan the image itself for those. For a
release, the attested SBOM comes from the same lockfile, by the same
steps, as the `filemorph-vX.Y.Z.cdx.json` attached to the release.

Verify with the [GitHub CLI](https://cli.github.com/), logged in to any
GitHub account (`gh auth login`):

```bash
gh attestation verify oci://ghcr.io/mrchenglen/filemorph:1.2.3 \
  --owner MrChengLen \
  --signer-workflow MrChengLen/FileMorph/.github/workflows/docker.yml \
  --source-ref refs/tags/v1.2.3 \
  --predicate-type https://cyclonedx.org/bom
```

- `--predicate-type` is required: by default `gh` accepts only SLSA
  build-provenance attestations, and the check fails.
- `--signer-workflow` and `--source-ref` accept only an attestation that
  `docker.yml` made for a push of that tag. After [verifying the
  tag](#verifying-a-release-tag), also add
  `--source-digest "$(git rev-parse 'v1.2.3^{commit}')"` in that clone:
  it ties the attestation to the commit the tag's signature covers, so an
  image built after the tag was moved to another commit fails.
- For the office image, verify `filemorph:1.2.3-office`. `:latest` and
  `:office` move with every build of `main` and every release; verify
  them with the ref of the build that pushed them: `--source-ref
  refs/heads/main`, or `refs/tags/vX.Y.Z` right after a release.
- `--bundle-from-oci` reads the attestation from GHCR instead of the
  GitHub API.
- To print the attested SBOM, add
  `--format json --jq '.[0].verificationResult.statement.predicate'`.

## First-time setup — generating the maintainer signing key

The recurring flow in the next section assumes you already have a GPG
signing key configured and its public block listed under "Maintainer
public keys". If this is the project's first signed release, do this
once (on your own machine — the *secret* key never leaves it):

```bash
# 0. Confirm GPG is installed.
gpg --version

# 1. Generate the key. In the prompts: choose "ECC (sign only)" →
#    Curve 25519 (or "RSA" → 4096 if you want maximum verifier
#    compatibility); set a 2–3 year expiry (renewable); pick a strong
#    passphrase. For the user ID use a PROJECT address you control —
#    it is baked into the public block forever — not a personal mailbox:
#       Real name: Lennart Seidel (FileMorph release signing)
#       Email:     releases@filemorph.io
gpg --full-generate-key

# 2. Note the fingerprint (the 40-hex string after "sec ...").
gpg --list-secret-keys --keyid-format=long

# 3. Export the PUBLIC block.
gpg --armor --export <FINGERPRINT>
#    Paste the entire -----BEGIN ... END PGP PUBLIC KEY BLOCK----- into
#    the "Maintainer public keys" section of this file, under your name,
#    and open a PR with that change.

# 4. Back up the SECRET key to encrypted offline media. Do NOT commit
#    it, do NOT put it in .env, do NOT paste it anywhere online — a
#    leaked signing key lets anyone forge a "trusted" release tag.
gpg --armor --export-secret-keys <FINGERPRINT> > filemorph-signing-secret.asc
#    Move filemorph-signing-secret.asc to an offline encrypted drive,
#    then securely delete the local copy.

# 5. (Optional) publish the public key so others can fetch it without
#    cloning the repo (keys.openpgp.org will email you to verify the UID).
gpg --keyserver hkps://keys.openpgp.org --send-keys <FINGERPRINT>

# 6. Tell git to sign tags with this key.
git config --global user.signingkey <FINGERPRINT>
git config --global tag.gpgsign true     # optional: sign every tag

# 7. Smoke-test before relying on it.
git tag -s v0.0.0-signing-test -m "signing test"
git verify-tag v0.0.0-signing-test       # must print "Good signature"
git tag -d v0.0.0-signing-test
```

Once the PR from step 3 merges, `release.yml`'s `git verify-tag` step
accepts tags signed with this key and the next `git tag -s vX.Y.Z`
produces a published release. Until at least one key block is present,
no release publishes — that fail-closed behaviour is intentional, not a
bug.

## Maintainer responsibilities

When cutting a release:

```bash
# Local — the GPG private key never leaves the maintainer's machine.
git tag -s vX.Y.Z -m "release vX.Y.Z"
git push origin vX.Y.Z
```

The push triggers two parallel workflows:

- [`docker.yml`](../.github/workflows/docker.yml) builds and
  cosign-signs the container image, and attests its SBOM to it.
- [`release.yml`](../.github/workflows/release.yml) verifies the
  tag against the keys below, builds the source tarball, and
  publishes the GitHub release with an `IMAGE_DIGEST.txt`
  pointing at the signed image, plus the CycloneDX SBOM. The SBOM
  is generated in a separate job that can only read the
  repository, by a generator installed from hash-pinned
  `requirements-sbom.lock`; the job that publishes installs nothing.

If the verification step fails (tag unsigned, signing key not
listed here), the release does not publish and the failure is
visible in the Actions UI.

## Maintainer public keys

Each maintainer adds their full ASCII-armored public key block
below their name. The release workflow imports every block it
finds inside this document, so adding or rotating a key is a
documentation PR.

If no key blocks are present below, releases will not publish until
at least one is added. Until the project transitions out of solo
development, this section may carry just one block.

<!-- Maintainer key blocks follow below. Each block is a complete
     ASCII-armored PGP PUBLIC KEY BLOCK, exported with
     `gpg --armor --export <FINGERPRINT>`. The literal BEGIN/END armor
     lines are deliberately not written out in this comment, so the
     release workflow's block extraction only ever matches the real
     key block(s) below. -->

### Lennart Seidel — `security@filemorph.io`

Ed25519 signing key. Added 2026-05-12; expires 2028-05-11. Fingerprint
`7D8D E1FE 7B8E 4F8E F75E B81C 3536 2AA5 F3C3 2EC2`. After importing this
block, `git verify-tag vX.Y.Z` on a release tag prints `Good signature`.

```
-----BEGIN PGP PUBLIC KEY BLOCK-----

mDMEagNiaRYJKwYBBAHaRw8BAQdAwJjgpeCS8wAu/M26EfIizocxWYw5RYX0dz5h
4nUM4oC0Jkxlbm5hcnQgU2VpZGVsIDxzZWN1cml0eUBmaWxlbW9ycGguaW8+iJkE
ExYKAEEWIQR9jeH+e45PjvdeuBw1Niql88MuwgUCagNiaQIbAwUJA8JnAAULCQgH
AgIiAgYVCgkICwIEFgIDAQIeBwIXgAAKCRA1Niql88Muwq+IAP9ORNtE7d2xjh/W
AB4OjtmDXSYZZg8ia4wdB5q9+VLVngEAw7/Q7pPK919nqtKK0zT+s55AfRN9kuKI
LWx1Q6p9TQ0=
=a6YT
-----END PGP PUBLIC KEY BLOCK-----
```


## Key rotation

When rotating a key:

1. Export the new public key (`gpg --armor --export <new-fingerprint>`).
2. Open a PR adding the new block above the old one.
3. Sign and push the PR using the **old** key so the tag-verify
   workflow still passes for the merge commit's release-tag
   workflow run (this matters only if the merge itself triggers a
   tag — typically merges go to `main` without a tag, so this
   ordering rarely binds).
4. After the rotation PR merges, the next release tag is signed
   with the new key and verifies cleanly.
5. The old key block stays in the file as long as any consumer
   might still want to verify a historical tag. Removal is
   appropriate when the historical tag is past its support window.

A revoked key (compromised, lost) gets a `[revoked]` annotation
above its block and is moved to a "Revoked keys (do not trust)"
section at the bottom of the file. The block stays so a consumer
who imports it sees the revocation rather than silently trusting
a compromised key.

## Out of scope

- **SSH-signed tags.** Git supports SSH-signed tags as of 2.34, but
  the GitHub Actions runner's `git verify-tag` does not by default
  resolve SSH `allowedSignersFile` from a doc — the workflow would
  need a separate import step. The current design uses GPG only;
  SSH-signing support can be added when a maintainer requests it.
- **Notary v2.** Sigstore is the chosen path because it is
  free-tier on GitHub Actions (OIDC token) and has working
  reproducible verification today; Notary v2 is on the watch list
  for OCI-spec maturity.
- **Reproducible builds.** Bit-for-bit reproducibility of the
  container image is a future goal (relevant for KRITIS / Air-Gap
  customers); not in NEU-B.4 scope.
