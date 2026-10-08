### Changed — veraPDF now blocks the merge, inside lint-and-test; duplicate CI runs removed

PDF/A-2b conformance now blocks the merge. The veraPDF gate ran as a workflow
of its own, `verapdf.yml`: it reported on every pull request, but nothing
required it, although the README and the pricing page call it a CI gate. Its
steps now follow the test run in `lint-and-test`, a check that merging into
`main` requires, and `verapdf.yml` is gone. The fixture is built from the
lockfile versions that job installs anyway, so the gate no longer sets up the
same environment a second time; the validator image stays pinned by digest
(`verapdf/cli` v1.30.2), now without network access and with the fixture
mounted read-only, and the fixture is still kept as an artifact, after a
failure too. A test holds both steps in that job, with no `if:` and no
`continue-on-error` to skip them.

One more duplicate and a dead trigger went. `sbom.yml` no longer runs on every push to `main`:
`docker.yml` builds the same SBOM there and attests it to the images, and the
90-day artifact the push produced had no reader. It remains a manual run that
rehearses the SBOM steps `release.yml` and `docker.yml` repeat. `ci.yml` and
`scope-guard.yml` no longer list a `develop` branch, which does not exist.

Dependabot's pip group, now `python-all`, takes every Python update instead of
only minor and patch ones. Dependabot gives a `requirements.txt` floor raise no
update type, so each still arrived as a PR of its own, #191 to #195 in one week,
and four of them turned `lint-and-test` red until `requirements.lock` was
recompiled. They now come as one weekly PR and one lockfile pass, after a
three-day cooldown. The caps on WeasyPrint (below 70), pikepdf and the SBOM
generator are held back by version range.
