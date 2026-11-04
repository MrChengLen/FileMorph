### Changed — Image builds set up signing before they push, sign each image once, and run by hand only on main

- The Docker workflow installs cosign before it builds and pushes, and gives
  signing three tries. The install failed after the push twice in October 2026
  and signing once, on a bad answer from GitHub; each time `:latest` and
  `:office` already pointed at an image nobody had signed.
- cosign 2.6.5 instead of 2.4.1: the newest release with the same signature
  format, so the `cosign verify` commands in the docs are unchanged.
- Each image is signed once, by its digest. It used to be signed once per tag,
  four signatures for the same digest; `cosign verify` by tag resolves the tag
  to that digest either way.
- A manual run on anything but `main`, another branch or a tag, fails at its
  first step, before it logs in: nothing is pushed, signed or attested. Its
  tags would otherwise have published that code as `:latest` and `:office`,
  signed, for the next deploy to pull. The step guards every ref that carries
  this change.
- The run's summary lists each image's digest and tags, and the exact
  `cosign verify` command for it.
- The build job's checkout no longer keeps the workflow token in the working
  copy; every checkout but the one that pushes recompiled lockfiles now does
  without it, and a test keeps it that way.
- `smoke-test (base)` and `smoke-test (office)` are required checks now, next
  to `lint-and-test`, `secret-scan` and `scope-check`: a pull request whose
  images do not start or fail their checks can no longer be merged.
