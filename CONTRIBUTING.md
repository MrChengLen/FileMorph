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

# 5. Run tests and lint
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
1. FileMorph version (`GET /api/v1/health`)
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

Every Python file in the project carries the SPDX header
`# SPDX-License-Identifier: AGPL-3.0-or-later`. Please preserve it in files
you modify, and add it to any new files you create.
