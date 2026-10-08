### Fixed — licence and install docs describe the pillow-heif wheel FileMorph ships

The code review of #164 found two claims about `pillow-heif` that were already
wrong on `main`:

- **Licence.** `docs/third-party-licenses.md` and `docs/tech-stack-rationale.md`
  said the wheel's metadata declares GPLv2 and that a `pip-licenses` or SBOM
  scan will flag it. That stopped being true with pillow-heif 1.6.0, which
  dropped the `GPLv2` classifier (upstream #455): the locked 1.8.0 declares only
  `BSD-3-Clause`, and `pip-licenses` and the release SBOM
  (`cyclonedx-py environment --PEP-639`, run over the locked wheels) report
  exactly that. The GPLv2 part — the `x265` HEVC encoder the binary wheel
  bundles next to `libheif` and `libde265` — is stated only in the wheel's
  `LICENSES_bundled.txt`, which neither scan reads. The docs now say so and
  what it means for operators: running FileMorph is not distribution;
  redistributing the image or the wheel passes `x265` on under GPLv2 and
  `libheif`/`libde265` under LGPL-3.0, with their source obligations; and an
  SBOM-driven review has to add all three by hand. They also say that `x265`
  is loaded with the bundled `libheif`, although FileMorph never calls an
  encoder. The libheif row of the native-library table no longer lists
  `libaom`, which the 1.8.0 wheel does not bundle, and names the copy HEIC
  decoding uses: the wheel's (Debian's `libheif1` only in the no-wheel
  fallback).
- **libheif minimum.** pillow-heif 1.8.0 compiles only against libheif 1.23.4
  or newer (an `#error` in its C source; upstream #480). `docs/formats.md`,
  `docs/installation.md` and `README.md` sent Linux users to their
  distribution's `libheif-dev`, the pentest report said pillow-heif requires
  a system libheif (now a dated correction note there, which also says that
  dpkg-based image scanners report Debian's unused `libheif1`/`libde265-0`
  but not the bundled copies), and the Dockerfile's comments called the
  system `libheif1` the decoder pillow-heif loads. None
  of them holds: the x86_64 and aarch64 wheels bundle their own libheif, and
  a source build needs one that many distributions don't package. Debian 13
  shipped 1.19.8; 1.23.4 came as a security update (DSA-6523-1, 2026-09-28),
  which is why the Dockerfile's `libheif-dev` fallback for architectures
  without a wheel still meets that minimum. Only the Dockerfile's comments
  change; its packages, and so the image, stay the same.

Two guards in `tests/test_docs_match_code.py`: one reads the installed wheel's
licence metadata and `LICENSES_bundled.txt` and checks the licence docs
against them; the other fails when `requirements.lock` moves pillow-heif away
from the version `docs/formats.md` gives the libheif minimum for, or when two
docs quote different minimums.
