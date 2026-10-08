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
and Ghostscript binaries, the HEVC libraries and — in the `office` image —
LibreOffice) and is reached only across a process boundary (FFmpeg,
Ghostscript and LibreOffice are invoked as separate programs) or a wrapper
boundary (`libheif` via `pillow-heif`, whose bundled GPL `x265` is loaded into
the process but never called — see below), neither of which makes FileMorph a
derivative work. Four items warrant attention from anyone redistributing the
artifact — the GPL `x265` encoder inside the `pillow-heif` binary wheel (the
package's metadata says BSD-3-Clause, so metadata-based licence scanners do
not report it), the GPL FFmpeg build and the AGPL-3.0 Ghostscript in the Docker
image, and the MPL-2.0 LibreOffice in the `office` image — all detailed below.

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
| **Permissive** — MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0, ISC, Unlicense/CC0, PSF-2.0, MIT-CMU (Pillow's HPND) | FastAPI/Starlette/Pydantic, Uvicorn, Jinja2, Pillow, pypdf, reportlab, WeasyPrint, Markdown, openpyxl, python-docx, mammoth, ffmpeg-python, SQLAlchemy/Alembic, asyncpg, python-jose, bcrypt, cryptography, stripe, Babel, slowapi, lxml, pillow-avif-plugin, requests (transitive, via `stripe`), … (the large majority) | No copyleft. Bundle, modify, redistribute closed-source freely; keep the copyright/notice text (each wheel ships its `LICENSE` file — those, plus the SBOM, are your notice manifest). |
| **Weak / file-level copyleft** — MPL-2.0 | `pikepdf` (PDF/A-2b output) — its wheels also bundle **qpdf**, which is Apache-2.0; `certifi` (CA bundle, transitive) | OK in a proprietary product: you must make the source of *the MPL-2.0 files* available (these are shipped unmodified, so pointing at the upstream sdist suffices) and you can't sublicense those files under other terms; the rest of your product is unaffected. |
| **Tri-licensed, pick-one** — GPLv2+ / LGPLv2+ / MPL-1.1 | `pyphen` (hyphenation, transitive via WeasyPrint) | Choose the LGPLv2+ or MPL-1.1 arm; not a constraint. |
| **BSD-3-Clause metadata, GPLv2 binary wheel** — invisible to metadata scanners | `pillow-heif` (HEIC input) | See the dedicated note below — `pip-licenses` and the release SBOM report BSD-3-Clause, so a metadata-based scan will **not** surface the GPLv2 `x265` encoder the wheel bundles; the explanation and mitigations matter. |

### `pillow-heif` — BSD-3-Clause metadata, GPLv2 binary wheel

The `pillow-heif` package metadata declares **`BSD-3-Clause`**, the licence of
pillow-heif's own Python and C source. Up to 1.5.0 the metadata also carried a
`GPLv2` licence classifier; 1.6.0 removed it (upstream #455).

The pre-built wheels that pip installs, and that the Docker image ships, bundle
a native stack under other terms: `libheif` (LGPL-3.0), `libde265` (LGPL-3.0,
HEVC *decode*) and `x265` (GPL-2.0-or-later, HEVC *encode*). Only the wheel's
`LICENSES_bundled.txt` says so — it gives the licence of the binary wheels as
GPLv2 "due to base library licenses" — and metadata scanners do not read that
file: `pip-licenses --from=mixed` and the release SBOM
(`cyclonedx-py environment --PEP-639`) both report pillow-heif as
**BSD-3-Clause** and nothing else. The `--gather-license-texts` option of
`cyclonedx-py environment` would copy the file's text into the SBOM; the
release workflow does not set it.

FileMorph uses `pillow-heif` for **HEIC input only** (Apple Photos exports →
other formats); decoding runs through `libde265`. `x265` is a link-time
dependency of the bundled `libheif`, so it is loaded into the FileMorph process
whenever `pillow-heif` is imported, but FileMorph never calls an encoder. To see
what an instance has loaded, run
`python -c "import pillow_heif; print(pillow_heif.libheif_info())"` inside the
container: it names the bundled `libheif` version, the `x265` encoder and the
`libde265` decoder.

What that means for an operator:

- **Running FileMorph**, self-hosted or as a service, is not distribution;
  GPLv2's conditions attach to distributing the software, and GPLv2 has no
  network-use clause like AGPL §13.
- **Redistributing** the Docker image, the installed virtualenv or the wheel
  (to a customer, onto an appliance, into an air-gapped bundle) passes `x265`
  on under GPLv2 and `libheif` and `libde265` under LGPL-3.0: keep
  `LICENSES_bundled.txt` with it and provide the corresponding source of all
  three, or a written offer for it, as those licences require. The file only
  links upstream release tags; a link is not such an offer, and the tag need
  not match the bundled build exactly (`libheif_info()` shows what is loaded).
- **An SBOM-driven licence review** will not see them. Add `libheif`,
  `libde265` (LGPL-3.0) and `x265` (GPL-2.0-or-later) under `pillow-heif` by
  hand, or have your scanner read the licence files in each package's
  `.dist-info/` (for pillow-heif, `.dist-info/licenses/LICENSES_bundled.txt`).
- **A GPL-free artifact** (some KRITIS / high-assurance procurement) needs
  `pillow-heif` built from source — `pip install --no-binary pillow-heif` —
  against a system `libheif` without an `x265` encoder, at the cost of any
  future HEVC-encode capability, or HEIC input dropped entirely. Each is a
  build-time choice with no code changes; raise it in the pilot conversation
  if it applies. The system libheif has to be libheif 1.23.4 or newer, or the
  build stops with an error (see the HEIC note in [`formats.md`](./formats.md)).
  Debian packages libheif's `x265` encoder as a separate plugin that is only
  recommended, so `apt-get install --no-install-recommends libheif-dev` gives
  an `x265`-free `libheif`; Debian 13 shipped 1.19.8, and 1.23.4 came as a
  security update (DSA-6523-1, 2026-09-28) that a default apt setup installs.
  Such a build loads the system libheif, which is then patched through the
  distribution. The image's FFmpeg contains `x265` as well (see below), so a
  GPL-free image needs both changes.

### `pillow-avif-plugin` — the bundled AV1 codec stack

FileMorph uses `pillow-avif-plugin` for AVIF input **and** output — unlike
`pillow-heif`, whose bundled HEVC encoder FileMorph never calls, the plugin's
AV1 encoder is used. PyPI's package metadata classifies it **MIT**; the
`LICENSE` file the wheel ships
is worded as a standard BSD-2-Clause notice (same permissive family,
functionally interchangeable — the classifier is what an automated scanner
reports, so it's the label used here). That same file bundles the licences
of the native libraries the wheel embeds:

- **libavif** (the AVIF container/codec wrapper) — BSD-2-Clause.
- **dav1d** (AV1 decoder; the `obu.c` file specifically) — BSD-2-Clause,
  copyright VideoLAN and dav1d authors.

libavif can additionally build against **aom** (the AV1 reference
encoder/decoder, BSD-2-Clause plus the Alliance for Open Media patent
licence), **rav1e** (BSD-2-Clause) and **SVT-AV1** (BSD-3-Clause-Clear) as
alternative codec backends — all permissive, none copyleft — but the
installed wheel's bundled licence file only itemises libavif and dav1d by
name, so treat the other three as "present if your platform's wheel links
them" rather than independently confirmed here. Verify against the wheel
you actually ship with `pip show pillow-avif-plugin` and the `LICENSE`
file in its `dist-info`.

## Native / system libraries in the Docker image

The image (`python:3.14-slim` base) adds, via `apt`, the native pieces the
converters need:

| Component | Licence | How FileMorph reaches it | Implication |
|---|---|---|---|
| **FFmpeg** (Debian package) | Debian builds FFmpeg with `--enable-gpl` (x264, x265, …) → effectively **GPL-2.0+** (GPL-3.0+ for `--enable-version3` parts) | Invoked as a **separate program** via `ffmpeg-python` subprocess calls — never linked into the FileMorph process | Calling a separate GPL program does not make the caller a derivative work, so **FileMorph's own licence is unaffected**. The *Docker image*, as a bundle, does contain GPL software — a redistributor of the image carries the GPL source-availability obligation for the FFmpeg component (Debian's source archive satisfies it). A "no GPL anywhere in the deployed artifact" requirement needs a custom image with an LGPL-only FFmpeg build (`--disable-gpl`, reduced codec set) — available on request. |
| **libheif**, twice: the copy bundled in the `pillow-heif` wheel, and Debian's `libheif1` | Bundled copy: `libheif` and `libde265` LGPL-3.0, `x265` GPL-2.0-or-later (see the `pillow-heif` note above). Debian's `libheif1`: `libheif` LGPL-3.0, plus the two decoder plugins it depends on — `libheif-plugin-libde265` (`libde265`, LGPL-3.0) and `libheif-plugin-dav1d` (`dav1d`, BSD-2-Clause). Debian's `x265` plugin for libheif is only recommended, and the image does not install it. | On amd64 and arm64, HEIC decode uses the **bundled** copy: the `pillow-heif` wheel loads it from `pillow_heif.libs/` next to the package, not the system library, and nothing else in the image loads `libheif1`. `libheif1` is the runtime half of the Dockerfile's fallback for an architecture without a `pillow-heif` wheel (the builder stage installs `libheif-dev` to compile against it); only such a source-built `pillow-heif` loads it. | For HEIC, the bundled copy's terms apply — see the `pillow-heif` note above. `dpkg -l` lists only Debian's packages; the bundled libraries are the files in `/opt/venv/lib/python3.14/site-packages/pillow_heif.libs/`. |
| **qpdf** | Apache-2.0 | Bundled inside the `pikepdf` wheel (no system package) | Permissive — no obligation beyond notice. |
| **cairo / pango** (WeasyPrint rendering) | LGPL-2.1 | Dynamically linked as system shared libraries through WeasyPrint | LGPL via dynamic linking against unmodified system libraries is the standard, unproblematic case for proprietary use (the obligation is to allow relinking, which dynamic linking already does). |
| **Ghostscript** (`ghostscript` apt package) | AGPL-3.0 (Artifex's default public distribution; a commercial licence is also sold by Artifex) | Invoked as a **separate program** (`gswin64c`/`gs` subprocess) for the PDF/A-2b re-render path — never linked into the FileMorph process. Present in **both** the slim and office images (the office stage builds `FROM base`, which already installs it). | Same separate-program reasoning as FFmpeg above: driving an AGPL binary as a subprocess does not make the caller a derivative work, so FileMorph's own licence is unaffected. The *image*, as a bundle, does contain AGPL software — a redistributor carries the AGPL source-availability obligation for that component (Debian's source archive satisfies it). AGPL §13 (the network-use clause) is triggered by *modifying* the program: the image installs Debian's `ghostscript` package as shipped, and FileMorph runs that unmodified binary as a separate program, so §13 does not reach FileMorph. |
| **LibreOffice** (`libreoffice-core`, `libreoffice-writer`) | MPL-2.0 (The Document Foundation; some bundled components are LGPLv3+) | **Office image only** — invoked as a **separate program** (`soffice --headless --convert-to`) for the high-fidelity DOCX → PDF path; not present in the slim image at all. | MPL-2.0 is weak/file-level copyleft, same class as `pikepdf` above — and the subprocess boundary means it doesn't reach into FileMorph's own licensing regardless. A redistributor of the `office` image carries the same source-availability obligation as any bundled MPL-2.0 component (upstream source is public). |
| **Fonts** (`fonts-crosextra-carlito`, `fonts-liberation`, `fonts-dejavu-core`) | Each Debian package under its own font licence — the terms are in `/usr/share/doc/<package>/copyright` inside the image | **Office image only** — system fonts installed next to LibreOffice so Word documents render with the metrics they were written for (Carlito for Calibri, Liberation for Arial / Times / Courier, DejaVu as a broad-coverage fallback). | Data files, not linked code. A redistributor of the `office` image passes their licence notices on with the packages. |

## Vendored frontend assets

Two non-Python assets ship in `app/static/`, both permissive:

| Component | Licence | Notes |
|---|---|---|
| **Chart.js** `v4.4.0` (`app/static/vendor/chart.umd.min.js`) | MIT | Vendored unmodified from the upstream `dist/chart.umd.min.js` build; full upstream licence text, source URL and a SHA-256 of the vendored copy live in [`app/static/vendor/LICENSE-chartjs.md`](../app/static/vendor/LICENSE-chartjs.md). Used read-only by the admin cockpit's dashboard charts. |
| **Tailwind CSS** (`app/static/css/tailwind.<sha>.css`) | MIT (Tailwind Labs) | Self-hosted, not loaded from `cdn.tailwindcss.com`: `scripts/build-tailwind.sh` runs the official standalone Tailwind CLI against `tailwind.config.js` and the app's own templates, producing a purged, minified, content-hashed bundle that is committed under `app/static/css/` and ships from the deployment's own origin; CI only checks that the committed bundle is up to date. See [`docs/tailwind-build-setup.md`](./tailwind-build-setup.md). |

## What this means for the Compliance Edition / commercial licence

- The commercial licence lifts the **AGPL-3.0 §13 disclosure obligation on
  FileMorph's own code** — that is the project's to grant because the project
  holds the rights (own work + the contributor grant).
- It **does not, and does not need to, relicense the third-party components.**
  They keep their own terms — which, being permissive or weak/file-level
  copyleft, already allow embedding in a closed-source product. The licence
  buyer's only standing obligation toward them is to **preserve their notices**
  (the per-wheel `LICENSE` files plus the release SBOM are the manifest).
- Four copyleft components are present in the default artifact but do not
  affect FileMorph's licensing or normal operation. Two are GPL: the
  `pillow-heif` wheel bundles a GPLv2 HEVC encoder (`x265`) that is **never
  invoked** (HEIC is decode-only), and the Docker image bundles Debian's GPL
  FFmpeg, which FileMorph drives as a **separate program** (subprocess), not a
  linked library. The third is Ghostscript (AGPL-3.0, in both images), likewise
  a separate program, used unmodified as Debian ships it — which is why AGPL
  §13 (network use) does not reach FileMorph. The fourth is LibreOffice
  (MPL-2.0, weak copyleft, `office` image only), also a separate program.
  **The project's position:** the default build keeps the GPL components.
  Removing them would mean dropping H.264 encoding, a real product
  regression, and building `pillow-heif` from source instead of using its
  wheel (or dropping HEIC input) — all to chase a paperwork concern that the
  separate-program boundary and the never-invoked status already resolve.
  The GPL-free builds (LGPL-only FFmpeg; `pillow-heif` rebuilt `--no-binary`
  against an `x265`-free libheif 1.23.4 or newer) are offered **per
  Compliance agreement** for deployments with a hard zero-GPL-in-the-artifact
  requirement; they are not the default because they degrade the product for
  everyone else.
- No dependency forces FileMorph to drop the dual-license offering, and none
  did at any point in the project's history; the [`License Map`](./tech-stack-rationale.md#license-map)
  is updated in the same PR as any new dependency precisely to keep that true.

## How to verify

- **Machine-readable, full transitive list:** the CycloneDX-JSON SBOM
  `filemorph-{version}.cdx.json` attached to every GitHub release (generated by
  the `release` workflow with `cyclonedx-py environment`, over a clean install
  of `requirements.lock`). Run it through your existing licence/CVE pipeline.
- **Human-readable regeneration:**
  ```bash
  pip install pip-licenses
  pip-licenses --from=mixed --format=markdown --order=license --with-urls
  ```
  (run inside the project venv after
  `pip install --require-hashes -r requirements.lock` — that is the exact set
  the image ships, so the scan matches the artifact).
- **What neither scan shows:** as run above, both read package metadata only
  (`pip-licenses --with-license-file` would add pillow-heif's BSD
  `LICENSE.txt`, not its `LICENSES_bundled.txt`). A licence a wheel states only
  in a bundled file — `pillow-heif`'s GPLv2 `x265` — appears in neither; see
  the [`pillow-heif` note](#pillow-heif--bsd-3-clause-metadata-gplv2-binary-wheel).
- **Per-dependency rationale:** [`tech-stack-rationale.md` § License Map](./tech-stack-rationale.md#license-map).

**As of 2026-09-30** a scan of the locked dependency set on `main`
(`requirements.lock`, with `cyclonedx-py environment --PEP-639` as the release
workflow runs it) yields the distribution summarised above: by declared
metadata the runtime tree is permissive or MPL-2.0 throughout except the
tri-licensed `pyphen`. That includes `pillow-heif`, which the scan reports as
BSD-3-Clause although its binary wheel bundles GPLv2 `x265` (see above), and
`pillow-avif-plugin` (MIT / BSD-2-Clause-style), documented separately above.

**The CycloneDX SBOM attached to the `v1.1.0` GitHub Release predates this**
— it was generated before the lockfile-parity (#146) and SBOM-generation
hardening (#163) changes, so it does not reflect `main`'s current dependency
set or the current SBOM pipeline. Until the next tagged release publishes a
fresh one, regenerate the SBOM locally against the current `requirements.lock`
(see "How to verify" above) rather than treating the `v1.1.0` attachment as
current. Re-run the SBOM and this scan on every release; flag any new
copyleft entry in the `License Map` and here.

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
