### Security — a release's cosign command accepts only that release's image build

A security review found that the `cosign verify` command `release.yml` writes
into each release's `IMAGE_DIGEST.txt` matched the signer against
`^https://github\.com/MrChengLen/FileMorph/`. Every workflow in the repository
passes that, at every ref: an image `docker.yml` built from `main`, or from a
branch it was dispatched on, would have verified as the release, and so would
a signature from any other workflow. The command also verified the tag, which
can later be moved to another image.

- **One signer.** The command now passes `--certificate-identity
  'https://github.com/MrChengLen/FileMorph/.github/workflows/docker.yml@refs/tags/vX.Y.Z'`,
  the exact subject Sigstore writes into the certificate when `docker.yml`
  signs for that tag. Checked against the published v1.1.0 images: all ten
  signatures (slim and office) carry that subject, while a build of `main`
  (checked on `latest`) carries `…/docker.yml@refs/heads/main`, which the new
  command rejects.
- **The digest, not the tag.** It verifies
  `ghcr.io/mrchenglen/filemorph@sha256:…` when the release job resolved the
  digest, as it did for v1.1.0. Otherwise it falls back to the tag and tells
  the reader to pull the digest cosign reports, not the tag.
- **Docs.** `docs/release-signing.md`, `docs/patch-policy.md`,
  `docs/self-hosting.md` and the comment in `docker.yml` quote the same form;
  `self-hosting.md` verifies a release instead of the moving `:office` tag.
  `release-signing.md` also shows how to tie the signature to the commit the
  tag's GPG signature covers (`--certificate-github-workflow-sha`). v1.1.0's
  `IMAGE_DIGEST.txt` predates this and keeps the old command; the docs say to
  verify v1.1.0 with the new one.

`release.yml` only runs on a signed tag, so `tests/test_supply_chain_hygiene.py`
runs the step's script with sample values (digest resolved, empty and
malformed). It fails if the command widens the signer, verifies the tag
although a digest was resolved, or `docker.yml` stops signing; each of seven
simulated regressions fails it. A second guard fails if a public doc shows a
`cosign verify` that verifies a tag or does not pin the signing workflow.
