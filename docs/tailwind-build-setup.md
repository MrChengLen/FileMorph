# Tailwind CSS — Self-Hosted Build

FileMorph ships a locally-built, purged Tailwind bundle under
`app/static/css/` instead of loading `cdn.tailwindcss.com` at runtime.
This keeps the Web UI working with a strict Content-Security-Policy
(no external CDN in `script-src` / `style-src`), eliminates a
third-party request on every page load, and removes the only external
dependency from the privacy-policy sub-processors list.

The filename is **content-hashed** — `tailwind.<sha256-prefix>.css` —
so `CachingStaticFiles` (in `app/main.py`) serves it with
`Cache-Control: public, max-age=31536000, immutable`. Browsers cache
it forever, and every rebuild rotates the hash so stale cache never
serves the wrong CSS. The runtime resolver that turns the hash into a
filename lives at `app/core/assets.py::tailwind_css_filename()` and is
wired into Jinja via `templates.env.globals["tailwind_css"]`.

## One-shot rebuild

```bash
bash scripts/build-tailwind.sh
```

The script auto-detects your host (Linux / macOS / Windows, x64 / arm64) and
downloads the matching Tailwind standalone CLI binary into `.tools/` (which is
gitignored) on first run — and again whenever the binary there doesn't match
its pin. Each download is verified against the SHA-256 pinned in the script
(taken from the release's `sha256sums.txt`) before it becomes executable. The
script then runs it against `tailwind.config.js` to produce an intermediate
`.tailwind.build.css`, hashes it and renames it to `tailwind.<sha>.css`. Any
prior hashed bundle in the directory is purged so only the current one ships.

No Node.js, no npm, no `node_modules/`. The standalone CLI is a single
statically-linked executable published by the Tailwind team; its output
is byte-identical to the npm-based CLI.

## When to re-run

Re-run `scripts/build-tailwind.sh` after any change that can introduce a
new utility class:

- editing templates in `app/templates/**/*.html`
- adding or removing class names in `app/static/js/**/*.js`
- changing `tailwind.config.js` (e.g. a new brand color)

Tailwind scans the `content` globs configured in `tailwind.config.js` and
emits only the classes actually referenced, so the output is small
(~25 KB minified today). If nothing user-visible changed, the rebuild
produces the same bytes and therefore the same hash — no churn.

Forgetting the rebuild is not silent: the CI freshness gate (below) fails
the pull request.

## What lives where

| Path | Purpose | Committed? |
|---|---|---|
| `tailwind.config.js` | Content globs + brand-color extension | yes |
| `app/static/css/tailwind.input.css` | Entry file — just the three `@tailwind` layers | yes |
| `app/static/css/tailwind.<sha>.css` | Minified, purged, content-hashed output | yes |
| `app/static/css/style.css` | Tiny hand-written overrides | yes |
| `scripts/build-tailwind.sh` | Build script — downloads + verifies CLI, runs it, hashes + renames | yes |
| `app/core/assets.py` | Runtime filename resolver (`tailwind_css_filename()`) | yes |
| `.tools/tailwindcss*` | The CLI binary itself (~40 MB) | no (`.gitignore`) |

## CI

The `Tailwind bundle freshness gate` step in `.github/workflows/ci.yml`
runs the build for every pull request into `main` and every push to `main`,
and fails if the result differs from the committed bundle (someone edited a
template, didn't rebuild, hash didn't rotate):

```yaml
- name: Tailwind bundle freshness gate
  id: tailwind
  run: |
    bash scripts/build-tailwind.sh
    changes="$(git status --porcelain -- app/static/css/)"
    if [ -n "$changes" ]; then
      printf '%s\n' "$changes"
      echo "::error::The committed Tailwind bundle is stale. ..."
      exit 1
    fi
```

`git status --porcelain` over the whole `css/` directory catches any rename,
creation, or deletion introduced by the rebuild: a rotated hash shows the
deleted old bundle as a tracked change and the new one as untracked. It runs
on its own line so that a failing `git` aborts the step instead of passing it.
The fix is always the same: run `bash scripts/build-tailwind.sh` locally and
commit `app/static/css/`. If your local build still differs from CI's, note
that Tailwind also scans untracked files under `app/templates/` and
`app/static/js/`, which CI never sees; the failing run uploads its own bundle
as the `tailwind-bundle-ci-built` artifact. The `tests/test_no_external_cdn.py`
suite enforces the rest at runtime: that exactly one `tailwind.<sha>.css` is
committed, that it's served with `immutable` Cache-Control, and that
`base.html` links the committed filename.

## Pinning the Tailwind version

`scripts/build-tailwind.sh` pins `VERSION="v3.4.17"` and the SHA-256 of each
platform binary. Bumping it is a deliberate commit — review the Tailwind
changelog first, then edit the variable, replace the SHA-256 pins with the
values from the new release's `sha256sums.txt`, rebuild (the hash will
change), and commit the new hashed bundle. Don't auto-track `latest`; a
Tailwind point-release could shift class output and silently change the
rendered UI across the whole site.
