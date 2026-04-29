# Sprint S1 — Technology First (Done-List)

*Stand: 2026-04-24 · Motto: `CLAUDE.md` §Technology First*

A wave of backend-hygiene, bandwidth-awareness, observability, and static-asset
hardening shipped under the Technology-First motto. Recorded here (not in
`docs/open-tasks.md`) because these items were never priority-ranked backlog
tickets — they came out of a live tech audit. Keep for historical context when
reading the affected code.

---

## Shipped

| Tag | Commit | What | Why |
|---|---|---|---|
| S1-A | `daefe10` | Event-loop-safe encoding · gzip · DB-pool hygiene · PNG squeeze | Every synchronous C-binding call now runs in `asyncio.to_thread`; a single slow convert stops blocking every other user |
| S1-B | `78acb98` | Per-tier output cap (bandwidth amplification guard) | Small input → huge output is the one path that bypasses the upload-size quota; new `max_output_size_mb` closes it |
| S1-B.fix | `f29bc9d` | Right-size Business/Enterprise output cap to 500 MB | Earlier 2 GB cap would have OOM-killed a small-RAM server under concurrent batches |
| S1-C | `b61d29a` | Static-cache headers + smart-format warning UI | `CachingStaticFiles` class serves `/static/*` with short revalidate by default, far-future `immutable` for hashed names; UI warns when a lossy-→-lossless reconvert would balloon the file |
| S3 | `8adfc84` | `FileResponse` + `BackgroundTask` streaming | Output no longer buffered in RAM — critical for 500 MB Business uploads |
| S4-foundation | `edeb4c4` | Structured logs: tier + rejection events | PII-free JSON log lines (tier/format/size only); builds the base for later billing + metrics |
| S1-D | `04f4f01` | Batch UI in the web app (multi-file + ZIP download) | API had `/convert/batch` for months; UI only ever posted one file. Closed the silent capability gap |
| S1-E | `5b9b361` | `/ready` probe + `uvicorn --timeout-keep-alive 65` | Distinguishes "container alive" from "DB pool alive"; keep-alive sized above typical CDN 60 s idle so connections survive a full idle window |
| S1-F | `a03f557` | Self-hosted Tailwind — drop `cdn.tailwindcss.com`, tighten CSP | `script-src 'self'` (no CDN allowance), removed the inline-config SHA-256 hash, standalone Tailwind CLI under `.tools/` |
| scope-scrub | `303c3fa` | Scrub production-server specifics from public comments | Pre-Commit Scope-Check rule from `CLAUDE.md` — generic wording for RAM sizing + CDN idle timeout |
| S1.5 | `ccca957` | `API_BASE` split — heavy upload POSTs to optional separate subdomain | Lets the main site sit behind a proxy with a body-size cap while uploads bypass it via a tunnel subdomain; zero-config same-origin default keeps tests + dev unchanged |
| S1-G | `75b0c11` | Cache-busting hash on tailwind bundle | `tailwind.<sha>.css` picked up by `CachingStaticFiles` regex → `Cache-Control: public, max-age=31536000, immutable`. Browsers cache forever; a rebuild rotates the filename |

All commits landed on `main` with individual CI green; audited as one batch
(Datenschutz / Security / Frontend / Backend / Tech) before push.

---

## Server-side / dashboard-only (tracked, not in the app)

Not in this repo because they configure the deployment, not the app:

- `uvicorn --workers 2` — RAM-budget call; needs server-side observation first.
- CDN proxy flip for the main site (DDoS / WAF / hidden origin IP). Blocked only
  on the app side by S1.5 (done); flip is a DNS toggle once uploads route
  through the separate subdomain.
- Prometheus / Grafana stack — deferred to observability sprint; `/metrics`
  endpoint wiring is app-side but live value needs a scrape target.
- Edge rate-limiting rule on `/api/v1/(convert|compress|morph)`. Redundant with
  slowapi but cheap Layer-7 insurance.

---

## Deferred to S2 (Morph + Smart-Tech)

Explicitly out of scope for S1, queued as the next decision point:

- `/api/v1/morph` — structural file adjustments (resize / crop / split / trim /
  strip-EXIF / compress-to-target). "Morph > Convert" per the motto.
- Compress-to-target-size via binary search (already scaffolded in the
  compressor; surface as a first-class option).
- Smart output routing — auto-pick AVIF / WebP based on `Accept:` header.
- Size-preview before upload (client-side estimate).
- Problem-centric preset tiles on the landing page (e.g. "shrink this to fit an
  email attachment") instead of format-list cards.

---

## Cross-References

- Motto: `CLAUDE.md` §Technology First
- Commit range: `98020dc..75b0c11` on `main`
- Priority-ranked backlog: `docs/open-tasks.md`
- Business-model alignment: `memory/business_model.md`
