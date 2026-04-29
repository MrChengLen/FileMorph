# FileMorph — Engineering & Product Assessment

**Date:** 2026-04-20  
**Authors:** Senior Developer Review + Senior Product Manager Review  
**Scope:** Codebase maturity, test strategy, CI/CD, GitHub structure, business case

---

## 1. Application Functionality

FileMorph is a **file conversion and compression REST API** with an integrated web UI.

### Core Capabilities

| Category | Formats | Implementation |
|---|---|---|
| **Images** | HEIC, JPG, PNG, WebP, BMP, TIFF, GIF, ICO | Pillow + pillow-heif |
| **Documents** | DOCX→PDF, DOCX→TXT, TXT→PDF, PDF→TXT | python-docx, pypdf, reportlab |
| **Markdown** | MD→HTML, MD→PDF | markdown + WeasyPrint |
| **Spreadsheets** | XLSX↔CSV, CSV↔JSON | openpyxl |
| **Audio** | MP3, WAV, FLAC, OGG, M4A, AAC, WMA, Opus | pydub + ffmpeg |
| **Video** | MP4, MOV, AVI, MKV, WebM, FLV, WMV | ffmpeg-python |
| **Compression** | JPG, PNG, WebP, TIFF (quality), MP4, MOV, AVI, MKV (CRF) | Pillow / ffmpeg |

### Request Flow

```
Browser/API Client
       │
       ▼
X-API-Key header ──► app/core/security.py (SHA-256 hash + hmac.compare_digest)
       │
       ▼
slowapi rate limiter (10/min convert, 30/min health, 120/min formats)
       │
       ▼
app/api/routes/convert.py or compress.py
  1. Extension extracted
  2. UUID temp filename created (no PII on disk)
  3. File written to /tmp/ff_<random>/
  4. Magic-byte validation (blocks PE, ELF, shell scripts)
  5. Converter/compressor invoked
  6. Output read into BytesIO
  7. Temp dir deleted
  8. Response streamed to client
       │
       ▼
Content-Disposition: attachment; filename="<original_stem>.<target_ext>"
```

### Security Posture (as of v1.0.2)

| Control | Implementation | Status |
|---|---|---|
| Authentication | SHA-256 hashed API keys, hmac.compare_digest | ✅ |
| Path traversal | Path.name + UUID temp filenames | ✅ |
| Magic-byte check | MZ / ELF / shebang / PHP headers blocked | ✅ |
| Exception hiding | Generic messages, server-side logging only | ✅ |
| Security headers | nosniff, X-Frame-Options, CSP, Referrer-Policy | ✅ |
| CORS | Restricted to localhost by default | ✅ |
| Rate limiting | Per-endpoint, in-memory (single-instance only) | ⚠️ |
| WeasyPrint SSRF | url_fetcher blocked | ✅ |
| GDPR temp files | UUID stems, no PII in filesystem paths | ✅ |
| Docker non-root | USER appuser (added in this release) | ✅ |
| Dependency CVEs | Pillow ≥10.3.0, python-multipart ≥0.0.18 | ✅ |

---

## 2. GitHub Structure and Access Permissions

### Repository Architecture

```
MrChengLen/FileMorph          ← PUBLIC (AGPLv3)
│  Community Edition — self-hostable, all core conversion features
│  No account/billing/storage code — safe to be public
│
├── main                      ← stable, tagged releases (protected)
├── develop                   ← integration branch (recommended, not yet created)
└── feature/*                 ← feature branches (merged via PR)

MrChengLen/filemorph-cloud    ← PRIVATE (Commercial License)
│  SaaS layer: user accounts, JWT auth, PostgreSQL, Stripe billing, R2 storage
│  Extends the public repo; never merges back

MrChengLen/filemorph-enterprise ← PRIVATE (Commercial License)
│  Enterprise features: SSO/SAML, LDAP, RBAC, Audit Log, White-Label
│  Delivered as Docker image layer on top of community edition
```

### Access Model

| Role | Access | Scope |
|---|---|---|
| Public / Community | Read, Fork, Clone, PR | `filemorph` (public) |
| Repo Owner (MrChengLen) | Full admin | All repos |
| Future team members | Collaborator (push, no admin) | As needed per repo |
| Enterprise customers | Docker image delivery only | No source access |
| CI/CD (GitHub Actions) | `GITHUB_TOKEN` (auto) | Read + write artifacts |

### Branch Protection (Recommended — not yet configured)

For `main` on the public repo, enable:
- **Require status checks to pass** before merging (`lint-and-test` workflow)
- **Require at least 1 review** before merge (when team grows)
- **Dismiss stale reviews** on new commits
- **No force-push** to main

```
Settings → Branches → Add rule → Branch name: main
☑ Require a pull request before merging
☑ Require status checks to pass (lint-and-test)
☑ Require branches to be up to date before merging
☑ Restrict who can push to main: owner only
```

### GitHub Actions CI/CD

```yaml
Trigger: push to main/develop, PR to main

Jobs:
  lint-and-test:
    1. Install system deps (ffmpeg, libheif, WeasyPrint libs)
    2. pip install -r requirements-dev.txt
    3. ruff check .              ← lint (blocking)
    4. ruff format --check .     ← format (blocking)
    5. pip-audit                 ← CVE scan (non-blocking, warning only)
    6. pytest tests/ -v          ← full test suite (blocking)

Separate workflow (on tag v*):
    Build Docker image → push to ghcr.io/mrchenglen/filemorph
```

### GitHub Secrets Required

**Community Edition (current):** None — no secrets needed.

**Cloud Edition (future, private repo):**
```
STRIPE_SECRET_KEY
DATABASE_URL
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
JWT_SECRET_KEY
SENTRY_DSN
```

---

## 3. Business Case and Implementation Strategy

### Market Position

FileMorph occupies a gap between consumer tools (Zamzar, CloudConvert) and enterprise middleware:

| Dimension | CloudConvert | Zamzar | **FileMorph** |
|---|---|---|---|
| Pricing | 8–30 EUR/month | 9–99 USD/month | 7.99–24.99 EUR/month |
| Self-hostable | No | No | **Yes (AGPLv3)** |
| API-first | Partial | No | **Yes** |
| Open Source | No | No | **Community Edition** |
| Privacy (EU) | US-hosted | US-hosted | **EU-deployable, GDPR-ready** |

### Revenue Model — Open Core

```
Tier 0: Community (Self-Hosted, Free)
  → AGPLv3, all conversion features, no accounts
  → Purpose: GitHub stars, contributor trust, enterprise credibility

Tier 1: Cloud Free (Hosted, Free)
  → 25 conversions/day, ephemeral, API 500/month
  → Purpose: top-of-funnel, no credit card required

Tier 2: Cloud Pro (7.99 EUR/month)
  → 500 conversions/day, 7-day storage, API 10k/month
  → Primary revenue unit

Tier 3: Cloud Business (24.99 EUR/month)
  → Unlimited, 30-day storage, webhooks, team accounts (5 users)

Tier 4: Enterprise Self-Hosted (299–999 EUR/year)
  → Commercial license (no AGPL obligation), SSO, SLA
  → High-margin, low-volume, GDPR/healthcare customers
```

### Projection (Conservative, Year 1)

| Metric | Value |
|---|---|
| GitHub stars target | 500 (organic + Product Hunt) |
| Conversion to Pro (5%) | 25 users × 7.99 EUR = ~200 EUR/month |
| Conversion to Business (1%) | 5 users × 24.99 EUR = ~125 EUR/month |
| Enterprise licenses/year | 2 × 299 EUR = ~600 EUR/year |
| **Monthly recurring revenue** | **~375 EUR/month** |
| Infrastructure (R2 + DB + hosting) | ~40–80 EUR/month |
| **Break-even** | **Yes from day 1** |

Scales linearly with GitHub reach. 2,000 stars → ~1,500 EUR MRR.

### Implementation Phases

| Phase | Scope | Effort | Gate |
|---|---|---|---|
| **0 (done)** | Security hardening (Part A), web standards (Part B) | 3 days | — |
| **1** | DB layer + Auth + File Storage (Part C, C-1 to C-4) | 3–4 weeks | Cloud beta |
| **2** | Stripe billing + Quota enforcement (C-5, C-6) | 2 weeks | Paid tier |
| **3** | Dashboard + Account UI (C-7) | 2 weeks | Public launch |
| **4** | Enterprise features (C-9: SSO, RBAC, Audit) | 4 weeks | Enterprise sales |

---

## 4. Senior Developer Assessment

### Tests — Current State

The project already has `tests/` with:
- Auth endpoint tests (`test_api_auth.py`)
- Image conversion tests (`test_convert_image.py`)
- Document conversion tests (`test_convert_document.py`)
- Shared fixtures with API key setup (`conftest.py`)

**Coverage gaps filled in this release:**
- `test_security.py` — path traversal, magic-byte blocking, security headers, error handler behavior, Content-Disposition UUID check
- `test_core.py` — `validate_api_key` constant-time assertion, `safe_download_name` edge cases, quota consistency

### Should Tests Run in GitHub Actions?

**Yes. Unconditionally. This is non-negotiable.**

Rationale:
1. The CI already has the `pytest` step and all system dependencies (ffmpeg, libheif, WeasyPrint). Adding tests costs zero CI infrastructure.
2. A broken `main` branch on a public repo destroys trust faster than any bug. The GitHub CI badge must stay green.
3. Security tests as CI gates mean a regression in path traversal handling or magic-byte blocking is caught before merge — not in production.
4. For Enterprise customers evaluating self-hosting: a test suite is proof of engineering discipline. It's a sales artifact, not just a dev tool.

### Test Quality Assessment

| Aspect | Current | Target |
|---|---|---|
| Auth coverage | ✅ Good | — |
| Happy-path conversion | ✅ Image, document | Add audio/video (requires ffmpeg; use `pytest.mark.skipif`) |
| Security regression tests | ✅ Added now | — |
| Unit tests (utils, security) | ✅ Added now | — |
| Edge cases (empty file, huge file) | ❌ Missing | Phase 1 |
| Async endpoints | ⚠️ TestClient wraps sync | Acceptable for now |
| Mocked external services | N/A (no external calls) | — |

### Architecture Assessment

**Strengths:**
- Plugin-based converter registry (`@register` decorator) — adding formats requires one file, zero core changes
- Strict separation of concerns: converters know nothing about HTTP
- Temp dir lifecycle correctly managed (BytesIO before cleanup)
- Logging structured and centralized

**Technical debt to address before Phase 1:**
- Rate limiting is in-memory (`slowapi`) — breaks with multiple uvicorn workers. Add Redis backend before any horizontal scaling.
- `data/api_keys.json` is a single file — fine for Community Edition, but must be replaced by DB-backed keys before Cloud launch (already planned in C-3).
- No async database session in routes yet — the `app/db/base.py` stub is correct, but integration into routes needs careful dependency injection design.

---

## 5. Senior Product Manager Assessment

### Readiness Assessment

| Dimension | Status | Notes |
|---|---|---|
| Core product (conversion) | ✅ Shippable | 30+ format pairs, stable |
| Security (Community) | ✅ Hardened | A-1 to A-9 + v1.0.2 |
| CI/CD | ✅ Operational | lint + test on every push |
| Documentation | ✅ Good | API ref, self-hosting, formats |
| Privacy claim accuracy | ⚠️ Fix needed | Footer says "never stored permanently" — technically files touch disk via temp dir |
| Tests (blocking gate) | ✅ Now in CI | — |
| Accounts/billing | ❌ Not started | Phase 1–3 |
| Privacy policy | ❌ Missing | Required before any data collection |
| Terms of Service | ❌ Missing | Required before paid tier |
| Cookie/localStorage consent | ❌ Missing | Required for EU |

### GitHub Stars as the Primary KPI (pre-revenue)

For an open-core product, GitHub stars are the **leading indicator** for enterprise pipeline:
- Stars signal developer adoption → developers recommend to employers
- Stars are used by procurement as a proxy for "is this project alive?"
- 500 stars → credible for SME self-hosting conversations
- 1,000 stars → Enterprise decision-makers take notice
- 5,000 stars → inbound Enterprise inquiries without cold outreach

**Go-to-market sequence:**
1. Fix footer privacy claim (quick win, legal risk mitigation)
2. Publish to Product Hunt as a "Show HN: open-source file converter with a REST API"
3. Write a dev.to / Medium article: "How I built an open-source CloudConvert alternative"
4. Open a GitHub Discussions page for feature requests (community engagement signal)
5. Add a "Cloud" waitlist to the README (email capture, validates demand before building)

### Risk Register

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| WeasyPrint SSRF re-emerges via new Markdown extension | Low | High | url_fetcher blocks all external; pin WeasyPrint version |
| Rate limiting bypass (multi-worker) | Medium | Medium | Document known limitation; fix with Redis in Phase 1 |
| GDPR complaint from EU user | Low (pre-launch) | High | Privacy policy + DPA before any EU user data collection |
| Competitor forks AGPLv3 code for SaaS | Low | Low | AGPLv3 requires them to open-source → no real threat |
| Key CVE in Pillow or ffmpeg | Medium | Medium | pip-audit in CI now catches this automatically |

---

## 6. Fazit & Handlungsempfehlungen

### Immediate (before any public marketing)

1. **Fix footer claim** — Change "Files are processed in memory and never stored permanently" to "Files are processed server-side and deleted immediately after conversion." (Legally accurate, still privacy-positive.)
2. **Enable branch protection on `main`** — Require CI to pass before merge.
3. **Write a minimal Privacy Policy** — Even for Community Edition, document what the server logs (IP address, request timestamps) and for how long.

### Before Cloud Beta (Phase 1)

4. **Redis for rate limiting** — Replace in-memory slowapi with Redis backend before running more than one uvicorn worker.
5. **Stripe DPA** — Sign Stripe's Data Processing Agreement before the first EU payment.
6. **`develop` branch + PR workflow** — Protect `main`, merge only from `develop` via reviewed PRs.
7. **Cloudflare R2 EU region** — Mandate `eu` location hint for EU user file storage.

### Before Paid Tier Launch (Phase 2–3)

8. **Terms of Service** — Especially covering: acceptable use, data retention, liability limitations.
9. **SOC2 Type I** (aspirational) — Not required at launch but signals enterprise readiness.
10. **SLA definition** — Even "best-effort" is better than silence for Enterprise customers.

---

*Assessment prepared by: Engineering Lead + Product Management*  
*Next review: After Phase 1 completion (target: 4 weeks)*
