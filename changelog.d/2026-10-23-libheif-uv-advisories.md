### Security — libheif 1.23.6 through pillow-heif 1.8.1, uv 0.13.4 in the lockfile jobs

- pillow-heif 1.8.1 bundles libheif 1.23.6 (was 1.23.4). libheif 1.23.5 and
  1.23.6 are security releases, and HEIC uploads are decoded in the server
  process. Three of the fixes concern files FileMorph opens. A crafted file
  that declares a small picture but codes a much larger frame no longer makes
  the decoder allocate a buffer for that frame (GHSA-v8qw-hwjv-44hw, high;
  1.23.5 checks the HEVC parameter sets too). A JPEG 2000 palette box with no
  columns no longer allocates 65,535 entries, which nested boxes multiplied to
  about 330 MB for a 3 KB file (GHSA-9c75-9g8r-4728, medium): libheif parses
  these boxes in any file, also where it cannot decode JPEG 2000. A decoded
  image whose bit depth contradicts its configuration box or the other tiles
  of its grid is now refused (GHSA-vv35-6hxg-95x8, medium). Most of the other
  fixes are in decoders the pillow-heif wheels leave out (AV1, JPEG,
  JPEG 2000, uncompressed, FFmpeg), in sharp YUV, or in encoding, which
  FileMorph does not do with HEIC. Deployments that accept HEIC uploads should
  update.
- The lockfile jobs (`lockfile-drift` in CI and the `deps-lock` workflow)
  install uv 0.13.4. Older releases trust the emSign ECC Root CA - G3 in their
  bundled CA store, whose intermediate keys were compromised
  (GHSA-hq85-5cpj-mr62); certifi 2026.10.19 dropped the same root. These jobs
  take from PyPI the hashes that the image's hash-checked install trusts.
  Images built from the committed lockfile need nothing; whoever recompiles
  the lockfiles should use uv 0.13.4 or newer.
