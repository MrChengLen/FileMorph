# Third-Party Licenses

This document is the engineering inventory of the open-source licenses that
FileMorph bundles, and what they mean for the dual-license model. It is written
for:

- **Self-hosters and redistributors** who repackage or embed FileMorph and need
  to know which obligations travel with the artifact.
- **Contributors** adding a dependency, who need the bar a new license has to
  clear.
- **Procurement / legal reviewers** evaluating the Compliance Edition, whose
  recurring question is: *FileMorph's own code is AGPL-3.0 — can a commercial
  licence actually lift that, given everything it depends on?*

It is **not legal advice.** For a binding opinion on a specific redistribution
scenario, consult counsel — the machine-readable [CycloneDX SBOM](#how-to-verify)
attached to each release is the authoritative input to give them.

## Posture in one paragraph

FileMorph's **own code** is AGPL-3.0 with a commercial-relicensing option; the
project holds copyright in it (own work plus the inbound=outbound grant in
[`CONTRIBUTING.md`](../CONTRIBUTING.md)), so the commercial licence in
[`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md) is the project's to grant.
Every **Python dependency** in the runtime tree is permissive (MIT, BSD-2/3,
Apache-2.0, ISC, Unlicense, PSF, MIT-CMU) or weak/file-level copyleft (MPL-2.0)
— none is GPL/AGPL strong-copyleft *at the Python level*, so embedding the
dependency tree in a closed-source product is unconstrained beyond preserving
notices. The copyleft that exists lives in the **native layer** (the FFmpeg
binary, the HEVC libraries) and is reached only across a process boundary
(FFmpeg is invoked as a separate program) or a wrapper boundary (`libheif` via
`pillow-heif`), neither of which makes FileMorph a derivative work. Two items
warrant attention from anyone redistributing the artifact — `pillow-heif`'s
wheel metadata and the FFmpeg build in the Docker image — both detailed below.

## FileMorph's own code

| Component | Licence | Notes |
|---|---|---|
| FileMorph application source (this repository) | AGPL-3.0-only **+** commercial | Dual-licensed. The AGPL terms are in [`LICENSE`](../LICENSE); the commercial terms (Compliance Edition, OEM) in [`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md). Contributions are taken under AGPL-3.0 with an additional commercial-redistribution grant ([`CONTRIBUTING.md`](../CONTRIBUTING.md)) — that grant is what keeps the project as sole rights-holder and able to issue commercial licences. |

## Python dependencies

The per-dependency *rationale* (why this library over the alternatives, and its
licence) is the [`License Map` in `tech-stack-rationale.md`](./tech-stack-rationale.md#license-map).
The *complete, machine-readable* list — direct **and** transitive, with licence
fields — is the CycloneDX SBOM (`filemorph-{version}.cdx.json`) attached to each
GitHub release; feed that to your scanner. The summary by licence class:

| Licence class | Examples | Implication |
|---|---|---|
| **Permissive** — MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0, ISC, Unlicense/CC0, PSF-2.0, MIT-CMU (Pillow's HPND) | FastAPI/Starlette/Pydantic, Uvicorn, Jinja2, Pillow, pypdf, reportlab, WeasyPrint, Markdown, openpyxl, python-docx, mammoth, ffmpeg-python, pydub, SQLAlchemy/Alembic, asyncpg, python-jose, bcrypt, cryptography, stripe, Babel, slowapi, lxml, requests/httpx, … (the large majority) | No copyleft. Bundle, modify, redistribute closed-source freely; keep the copyright/notice text (each wheel ships its `LICENSE` file — those, plus the SBOM, are your notice manifest). |
| **Weak / file-level copyleft** — MPL-2.0 | `pikepdf` (PDF/A-2b output) — its wheels also bundle **qpdf**, which is Apache-2.0; `certifi` (CA bundle, transitive) | OK in a proprietary product: you must make the source of *the MPL-2.0 files* available (these are shipped unmodified, so pointing at the upstream sdist suffices) and you can't sublicense those files under other terms; the rest of your product is unaffected. |
| **Tri-licensed, pick-one** — GPLv2+ / LGPLv2+ / MPL-1.1 | `pyphen` (hyphenation, transitive via WeasyPrint) | Choose the LGPLv2+ or MPL-1.1 arm; not a constraint. |
| **Flagged for automated scanners** — wheel metadata declares GPLv2 | `pillow-heif` (HEIC input) | See the dedicated note below — an automated `pip-licenses`/SBOM scan **will** surface this; the explanation and mitigations matter. |
| **Build-time only — not in the runtime image, not a runtime dependency** — GPLv2 (with bundling exception) | `pyinstaller` + `pyinstaller-hooks-contrib` (used by the desktop-build workflow only) | PyInstaller's GPLv2 carries the standard exception permitting distribution of *bundled applications* without GPL-infecting them; it ships in neither the Docker image nor the server `requirements.txt`. The desktop executables it produces are covered by that exception. No effect on the server artifact or the Compliance Edition. |

### `pillow-heif` — why a scanner sees "GPLv2", and what it actually means

The installed `pillow-heif` distribution declares **`GNU General Public License
v2 (GPLv2)`** in its PyPI package metadata. The reason is the native stack the
pre-built wheels bundle: `libheif` (LGPL-3.0), `libde265` (LGPL-3.0, HEVC
*decode*), and `x265` (GPL-2.0+, HEVC *encode*) — the metadata reflects the
most-restrictive bundled component. The pillow-heif Python source itself has
historically been BSD-3-Clause; verify against the version you ship.

FileMorph uses `pillow-heif` for **HEIC input only** (Apple Photos exports →
other formats). HEIC decode exercises `libde265` (LGPL-3.0). The GPL-2.0+ `x265`
encoder is present in the wheel but FileMorph never invokes a HEIC-encode path.

A redistributor that needs a **GPL-free artifact** (some KRITIS / high-assurance
procurement) can install with `pip install --no-binary pillow-heif` against a
system `libheif` built without `x265` (decode-only), at the cost of any future
HEVC-encode capability — or drop HEIC input entirely. Either is a build-time
choice with no code changes; raise it in the pilot conversation if it applies.

## Native / system libraries in the Docker image

The image (`python:3.12-slim` base) adds, via `apt`, the native pieces the
converters need:

| Component | Licence | How FileMorph reaches it | Implication |
|---|---|---|---|
| **FFmpeg** (Debian package) | Debian builds FFmpeg with `--enable-gpl` (x264, x265, …) → effectively **GPL-2.0+** (GPL-3.0+ for `--enable-version3` parts) | Invoked as a **separate program** via `ffmpeg-python` / `pydub` subprocess calls — never linked into the FileMorph process | Calling a separate GPL program does not make the caller a derivative work, so **FileMorph's own licence is unaffected**. The *Docker image*, as a bundle, does contain GPL software — a redistributor of the image carries the GPL source-availability obligation for the FFmpeg component (Debian's source archive satisfies it). A "no GPL anywhere in the deployed artifact" requirement needs a custom image with an LGPL-only FFmpeg build (`--disable-gpl`, reduced codec set) — available on request. |
| **libheif** (`libheif-dev`) + HEVC backend | `libheif` LGPL-3.0; `libde265` (decode) LGPL-3.0; `x265` (encode) GPL-2.0+ | Used via the `pillow-heif` wheel's bundled copy for HEIC decode; the system `libheif-dev` is present for build/headers | Same as the `pillow-heif` note above — decode path is LGPL; the GPL encoder is present but unused. Check `dpkg -l | grep -E 'libheif|libde265|x265'` in your build. |
| **qpdf** | Apache-2.0 | Bundled inside the `pikepdf` wheel (no system package) | Permissive — no obligation beyond notice. |
| **cairo / pango** (WeasyPrint rendering) | LGPL-2.1 | Dynamically linked as system shared libraries through WeasyPrint | LGPL via dynamic linking against unmodified system libraries is the standard, unproblematic case for proprietary use (the obligation is to allow relinking, which dynamic linking already does). |

## What this means for the Compliance Edition / commercial licence

- The commercial licence lifts the **AGPL-3.0 §13 disclosure obligation on
  FileMorph's own code** — that is the project's to grant because the project
  holds the rights (own work + the contributor grant).
- It **does not, and does not need to, relicense the third-party components.**
  They keep their own terms — which, being permissive or weak/file-level
  copyleft, already allow embedding in a closed-source product. The licence
  buyer's only standing obligation toward them is to **preserve their notices**
  (the per-wheel `LICENSE` files plus the release SBOM are the manifest).
- Two GPL components are present in the default artifact but do not affect
  FileMorph's licensing or normal operation: the `pillow-heif` wheel bundles a
  GPL-2.0+ HEVC encoder (`x265`) that is **never invoked** (HEIC is decode-only),
  and the Docker image bundles Debian's GPL FFmpeg, which FileMorph drives as a
  **separate program** (subprocess), not a linked library. **The project's
  position:** the default build keeps both — removing them would mean dropping
  HEIC input and H.264/H.265 encoding, a real product regression, to chase a
  paperwork concern that the separate-program boundary and the never-invoked
  status already resolve. The GPL-free builds (LGPL-only FFmpeg; `pillow-heif`
  rebuilt `--no-binary` against an `x265`-free `libheif`) are offered **per
  Compliance agreement** for deployments with a hard zero-GPL-in-the-artifact
  requirement; they are not the default because they degrade the product for
  everyone else.
- No dependency forces FileMorph to drop the dual-license offering, and none
  did at any point in the project's history; the [`License Map`](./tech-stack-rationale.md#license-map)
  is updated in the same PR as any new dependency precisely to keep that true.

## How to verify

- **Machine-readable, full transitive list:** the CycloneDX-JSON SBOM
  `filemorph-{version}.cdx.json` attached to every GitHub release (generated by
  the `sbom` workflow with `cyclonedx-py environment`). Run it through your
  existing licence/CVE pipeline.
- **Human-readable regeneration:**
  ```bash
  pip install pip-licenses
  pip-licenses --from=mixed --format=markdown --order=license --with-urls
  ```
  (run inside the project venv, ideally after `pip install -r requirements.lock`
  for the exact pinned set).
- **Per-dependency rationale:** [`tech-stack-rationale.md` § License Map](./tech-stack-rationale.md#license-map).

**As of 2026-05-12** a scan of the locked dependency set
(`requirements.lock`) yields the distribution summarised above: the runtime
tree is permissive or MPL-2.0 throughout, with `pillow-heif` the single
GPLv2-declared wheel (HEVC encoder bundled, unused) and `pyinstaller` the only
other GPLv2 package (build-time, desktop-only, bundling-exception). Re-run the
SBOM and this scan on every release; flag any new copyleft entry in the
`License Map` and here.

## See also

- [`LICENSE`](../LICENSE) — the AGPL-3.0 text covering FileMorph's own code.
- [`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md) — the commercial /
  Compliance Edition terms.
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — the inbound=outbound + commercial
  grant on contributions.
- [`tech-stack-rationale.md`](./tech-stack-rationale.md) — why each dependency
  is in the tree, with the per-dependency License Map.
- [`patch-policy.md`](./patch-policy.md) — release artifacts, the SBOM
  attachment, dependency hygiene.
