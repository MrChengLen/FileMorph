# Contributing to FileMorph

Thank you for considering a contribution! FileMorph is open to improvements of any kind —
bug fixes, new converters, documentation improvements, and UI enhancements.

---

## Before you start

- Check [existing issues](https://github.com/MrChengLen/FileMorph/issues) to avoid duplicate work
- For large changes, open an issue first to discuss the approach
- For new format support, describe what library you plan to use

---

## Quick contribution workflow

```bash
# 1. Fork the repository on GitHub, then clone your fork
git clone https://github.com/YOUR_FORK/filemorph.git
cd filemorph

# 2. Create a feature branch
git checkout -b feature/add-epub-support

# 3. Set up the development environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env

# 4. Make your changes
#    User-visible change? Add changelog.d/<YYYY-MM-DD>-<topic>.md (see changelog.d/README.md)

# 5. Run tests and lint (the full list of CI checks is under "CI gates" below)
pytest tests/ -v
ruff check .
ruff format .

# 6. Commit and push
git add .
git commit -m "feat: add EPUB to TXT conversion"
git push origin feature/add-epub-support

# 7. Open a Pull Request on GitHub
```

---

## CI gates

Merging into `main` requires three green checks: **lint-and-test**,
**secret-scan** and **scope-check**. `lint-and-test`
([`ci.yml`](.github/workflows/ci.yml)) runs the steps below — run the ones
your change touches before you push:

- **Lint + format** — `ruff check .` and `ruff format --check .`
- **Python version** — `python scripts/check_python_version.py`: the
  Dockerfile, the workflows, `requirements.lock` and `pyproject.toml` must agree.
- **Template classes** — `python scripts/check_template_classes.py`: no Jinja
  expression glued into a class name in `app/templates/`.
- **Tailwind bundle** — after adding or changing classes in templates or JS,
  run `bash scripts/build-tailwind.sh` and commit `app/static/css/`. CI
  rebuilds the bundle and fails if anything in `app/static/css/` changes.
- **i18n drift** — after adding, changing or removing `_()` strings, run
  `python scripts/i18n.py extract`, then `python scripts/i18n.py update`,
  translate the new entries in `locale/de/LC_MESSAGES/messages.po` (the `en`
  catalogue needs a translation only where the source string is not English)
  and clear any `#, fuzzy` marks, since compiling skips fuzzy entries. Then run
  `python scripts/i18n.py compile` and commit `locale/`. CI runs
  `python scripts/i18n.py drift-check`.
- **Dependency audit** — `pip-audit -r requirements.lock` (CI adds the
  `--ignore-vuln` flags listed in `ci.yml`).
- **Tests** — `pytest tests/`. CI runs them on Python 3.14 with
  `requirements-dev.txt` constrained to the versions pinned in
  `requirements.lock`, so they test what the Docker image ships.

`secret-scan` runs the gitleaks secret scanner; `scope-check` rejects
operations files and internal documents, which do not belong in this public
repository. More checks run on pull requests without blocking the merge:
`lockfile-drift` (`requirements.lock` must match `requirements.txt` — see
[docs/development.md](docs/development.md)), the veraPDF validation of the
PDF/A-2b output, and `smoke-test (base)` and `smoke-test (office)`
([`docker-pr.yml`](.github/workflows/docker-pr.yml)), which build both Docker
images without pushing them and smoke-test each one.

---

## What we're looking for

**New converters** — additional format support is always welcome:
- PPTX → PDF (PowerPoint)
- PDF → images (page-by-page export)
- SVG → PNG/JPG
- RAW camera formats (CR2, NEF, ARW) → JPG
- EPUB ↔ PDF

**Bug fixes** — especially for edge cases in existing converters (corrupt files, unusual encodings, etc.)

**Documentation** — clearer installation instructions, more examples, translations

**UI improvements** — better usability, accessibility, or mobile layout

---

## Code style

- Follow the existing code structure — converters are classes, compressors are functions
- Use the `@register` decorator for new converters (see [Development Guide](docs/development.md))
- Keep functions focused — one converter, one responsibility
- No external state — converters receive paths, return paths
- All files must pass `ruff check .` and `ruff format --check .`

---

## Tests

- Every new converter should have at least one test in `tests/`
- Use the provided fixtures in `conftest.py` (client, auth_headers, sample files)
- Tests must pass locally and in CI before merging

---

## Commit messages

We use conventional commits loosely:

| Prefix | When to use |
|--------|-------------|
| `feat:` | New feature or converter |
| `fix:` | Bug fix |
| `docs:` | Documentation only |
| `test:` | Adding or fixing tests |
| `chore:` | Dependencies, config, CI |
| `refactor:` | Code change without behavior change |

Examples:
```
feat: add EPUB to TXT conversion
fix: handle PNG with transparency in JPEG conversion
docs: add PHP integration example to API reference
```

---

## Reporting bugs

Please include:
1. FileMorph version (the release tag or image tag you deployed)
2. Operating system and Python version
3. The file type / conversion you attempted
4. The error message or unexpected behavior
5. Steps to reproduce

Open an issue at: https://github.com/MrChengLen/FileMorph/issues

---

## License

FileMorph is dual-licensed under **AGPL-3.0** ([`LICENSE`](LICENSE)) and a
**Commercial License** ([`COMMERCIAL-LICENSE.md`](COMMERCIAL-LICENSE.md)) for
users who cannot meet the AGPL copyleft obligations.

By submitting a contribution (pull request, patch, or any content) you agree:

1. Your contribution is licensed under **AGPL-3.0** and becomes part of the
   public FileMorph open-source project.
2. You grant the FileMorph maintainers the **additional right to relicense
   your contribution under the Commercial License** described above. This
   allows the project to continue offering a commercial option to users
   whose deployment model is incompatible with AGPL copyleft (OEM,
   closed-source SaaS). Your contribution remains AGPL in the public repo —
   only the commercial relicensing path is granted.
3. You confirm you have the right to submit the contribution (either your
   own work, or cleared by your employer if applicable).

This is a lightweight inbound=outbound + commercial-grant model used by
projects such as Sentry, GitLab, and Grafana Labs. If you cannot agree to
clause 2, please open an issue first — we can work out a CLA-free alternative
(e.g. maintainer writes an equivalent patch) so your idea still gets in.

Python files carry the SPDX header
`# SPDX-License-Identifier: AGPL-3.0-or-later`. Please preserve it in files
you modify, and add it to any new files you create. The exceptions are the
files under [`app/ee/`](app/ee/README.md) and `tests/test_ai_redaction.py`:
that code is commercially licensed, not AGPL, and carries
`# SPDX-License-Identifier: LicenseRef-FileMorph-Commercial` instead.
