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

## Maintainer responsibilities

When cutting a release:

```bash
# Local — the GPG private key never leaves the maintainer's machine.
git tag -s vX.Y.Z -m "release vX.Y.Z"
git push origin vX.Y.Z
```

The push triggers two parallel workflows:

- [`docker.yml`](../.github/workflows/docker.yml) builds and
  cosign-signs the container image.
- [`release.yml`](../.github/workflows/release.yml) verifies the
  tag against the keys below, builds the source tarball, and
  publishes the GitHub release with an `IMAGE_DIGEST.txt`
  pointing at the signed image.

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

<!-- Maintainer key blocks begin here. Each block is a complete
     `-----BEGIN PGP PUBLIC KEY BLOCK-----` … `-----END PGP PUBLIC KEY BLOCK-----`
     section, exported with:
       gpg --armor --export <FINGERPRINT>
-->

<!-- TODO: insert maintainer key here on first signed release. -->

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
