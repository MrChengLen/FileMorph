### Security — Stripe calls and outgoing mail no longer trust the compromised emSign root

The certifi update fixed certifi's own CA bundle (GHSA-6q48-6c7w-9gw2). Two
other places FileMorph takes its trusted CAs from still held the emSign ECC
Root CA - G3, below which eight intermediate CAs had their keys compromised:

- **Stripe.** The Stripe SDK checks certificates against a CA file it ships
  itself, which still trusts this root and which no dependency audit covers.
  `app/core/billing.py` now points the SDK at certifi's bundle, the one
  pip-audit watches and `requirements.txt` keeps past the advisory.
  `tests/test_stripe_ca_bundle.py` pins what the SDK hands to `requests` on a
  call. This matters only where Stripe keys are configured.
- **The image's system CA store.** Outgoing mail (aiosmtplib) and anything
  else on Python's default TLS settings trust Debian's ca-certificates from
  the base image. The base image moves to the python:3.14-slim build of
  2026-10-21, whose ca-certificates 20250419+deb13u1 (DSA-6572-1) drops this
  root and the "Comodo AAA Services root". The same build brings Python
  3.14.8 and Debian's OpenSSL security update 3.5.7-1~deb13u3 (DSA-6531-1).
  The Docker PR smoke test now fails if the image's system CA store trusts
  the emSign root. Installed without the image, FileMorph's mail trusts the
  operating system's CA store: update its ca-certificates package.

pip's own copy of certifi in the image (pip 26.2.1 vendors 2026.6.17) still
holds the root. pip runs only while the image is built, and it installs only
packages whose hash matches `requirements.lock`.
