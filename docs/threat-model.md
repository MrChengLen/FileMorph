# Threat Model (STRIDE)

This document maps the STRIDE threat categories onto FileMorph's actual
controls and code anchors. It is the procurement-reviewer companion to
[`security-overview.md`](./security-overview.md): if the security overview
answers *what FileMorph does*, this file answers *what threats those
defences are aimed at*.

The model covers the application layer. Operating-system, container-runtime,
and reverse-proxy threats are the operator's responsibility — see
[`self-hosting.md`](./self-hosting.md) for the operational hardening
checklist that closes those.

## Scope

Threat-modelled assets:

- User-uploaded file content (in transit and during in-memory processing).
- User credentials (passwords, API keys, JWT session tokens — Cloud Edition).
- Account metadata (email, subscription tier, billing identifiers — Cloud Edition).
- Audit-relevant operational data (admin actions, structured logs).

Out of scope:

- Operating-system multi-tenant isolation (one-instance-per-tenant is the
  recommended pattern; see *Architecture*).
- Side-channel leaks inside Pillow / WeasyPrint / ffmpeg.
- Compromised client devices (XSS bypassing CSP, malware on the user's
  machine).
- Operator-level threats (rogue admin, hosting-provider compromise).

## STRIDE table

| Category | Concrete threat | Mitigation | Code / doc anchor | Residual risk |
|---|---|---|---|---|
| **S — Spoofing** | API caller pretends to hold a key they do not possess. | SHA-256-hashed key store; constant-time comparison via `hmac.compare_digest`. | `app/core/security.py::validate_api_key` | None known. Comparison is timing-safe. |
| **S — Spoofing** | Login as another user via stolen / replayed credential. | bcrypt password hash with adaptive cost; short-lived 15 min JWT access token + 30 day refresh token. | `app/core/auth.py::hash_password`, `create_access_token` | A leaked refresh token grants 30 days of access — operators should rotate `JWT_SECRET` on suspicion (invalidates all sessions). |
| **S — Spoofing** | Rate-limit bypass via spoofed `X-Forwarded-For`. | The application reads `X-Forwarded-For`; the reverse proxy must be configured to overwrite (not append) the header. | [`self-hosting.md`](./self-hosting.md) §trust-proxy, PT-006 anchor in security-overview | Self-hoster misconfiguration. CI-level guard not possible — operational hardening item. |
| **T — Tampering** | Malicious upload (PE, ELF, shell, PHP) reaches a converter. | Magic-byte deny-list rejects the request before any decoder runs; HTTP 415 returned. | `app/core/processing.py` (`BLOCKED_MAGIC`), enforced in `app/api/routes/convert.py` + `compress.py` | None known for the listed prefixes. |
| **T — Tampering** | Path traversal via filename injection. | Filenames never used as filesystem paths; UUID stems under a `fm_`-prefixed scratch dir. | `app/api/routes/convert.py` (temp-dir handling), PT-001 anchor | None known. |
| **T — Tampering** | Header injection via filename in `Content-Disposition`. | `safe_download_name()` strips ASCII-unsafe bytes and RFC 5987-encodes UTF-8. | `app/core/utils.py::safe_download_name`, PT-013 anchor | None known. |
| **T — Tampering** | SSRF via WeasyPrint URL fetching. | `url_fetcher=_deny_url_fetcher` denies every external fetch in WeasyPrint. | `app/converters/document.py::_deny_url_fetcher`, PT-008 anchor | Operator must not patch this out — documented as a do-not-disable hardening item. |
| **R — Repudiation** | User denies having performed a billable conversion. | Structured JSON logs record `operation`, `src_format`, `tgt_format`, `file_size_bytes`, `duration_ms`, `success` per request. | `app/core/logging_config.py`, structured-event schema in CLAUDE.md §Business-Metriken | Tamper-evident hash-chain not yet implemented — planned (compliance roadmap NEU-B). Until then, log integrity depends on storage controls. |
| **R — Repudiation** | Admin denies having performed a privileged action. | Cockpit actions (tier changes, role changes, deactivations) are logged with admin user-id, target user-id, and the change. | `app/api/routes/cockpit.py` | Same residual as above; full audit-trail with hash-chain is roadmap NEU-B. |
| **I — Info disclosure** | Internal exception details leak via API error response. | Global error handler returns a generic message; stack traces stay in server logs only. | `app/main.py::server_error_handler`, PT-004 anchor | None known. |
| **I — Info disclosure** | File contents written to disk under attacker-controlled name. | Files decoded into `BytesIO`; UUID-stem temp paths if disk is needed; `finally`-block cleanup; startup sweep for stale `fm_*` dirs >10 min. | `app/api/routes/convert.py`, `app/main.py::lifespan` | Temp dir contents during the converter run could be read by a co-tenant on a multi-tenant host — out of scope (one-instance-per-tenant pattern). |
| **I — Info disclosure** | Cross-origin JavaScript reads response headers it should not. | Strict CORS allow-list (never `*` with credentials); `expose_headers` listed explicitly. | `app/main.py` middleware, PT-003 anchor | None known. |
| **I — Info disclosure** | Inline `<script>` exfiltrates data via XSS. | CSP `default-src 'self'`, `script-src 'self' 'sha256-…'` pinning the only allowed inline block. | `app/main.py::_build_csp_header`, PT-005 anchor | API-key in `localStorage` is readable by any same-origin script (PT-010) — accepted trade-off, documented under *Known Limitations*. |
| **D — Denial of service** | Single client floods convert endpoint. | slowapi rate limit (10/min/IP) on `/convert` and `/compress`. | `app/core/rate_limit.py` | Multi-instance deployments split the bucket per worker — Redis backend is on backlog. |
| **D — Denial of service** | Decompression-bomb upload. | Pillow `MAX_IMAGE_PIXELS` enforced; per-tier output cap rejects oversized output post-conversion. | `app/core/quotas.py` | Per-batch aggregate cap not yet implemented — listed under *Known Limitations*. |
| **D — Denial of service** | Slow / oversized request body exhausts memory. | `Content-Length`-based pre-read rejection at `MAX_UPLOAD_SIZE_MB`. Operator-level cap at the proxy is recommended. | `app/main.py::limit_upload_size` | Slow-loris-style streaming attacks are the proxy's job. |
| **D — Denial of service** | Sync C-binding blocks event loop. | All synchronous binding calls (Pillow saves, WeasyPrint, pikepdf, ffmpeg) wrap in `asyncio.to_thread`. | `app/converters/*.py` | Pinned by lint discipline ("Event-Loop sauber halten" in CLAUDE.md). |
| **E — Elevation of privilege** | Stale JWT continues to grant admin after demotion. | Admin role rechecked against the `users` table on every cockpit request — token cannot escalate after a role change. | `app/api/routes/cockpit.py` | None known. |
| **E — Elevation of privilege** | Plugin loaded from untrusted source executes during conversion. | Converter plugins are loaded only from `app/converters/` (filesystem-bound), not from request input. | `app/converters/registry.py::_ensure_loaded` | Any third-party plugin pack a self-hoster installs runs with full app privileges — vet plugins before installing. |
| **E — Elevation of privilege** | Container escape via converter sub-process. | Converters run inside the application container; no container-escape primitives are exposed to user input. | Containerised deployment | OS-level isolation is the operator's responsibility — see compose-prod hardening (read-only rootfs, `cap_drop`, no-new-privileges) in the operations runbook. |

## Cross-references

- [`security-overview.md`](./security-overview.md) — full control catalogue,
  historical pentest findings (PT-001…PT-013), known limitations, and the
  operational hardening checklist.
- [`gdpr-privacy-analysis.md`](./gdpr-privacy-analysis.md) — data-flow
  analysis, retention semantics, sub-processor reasoning under GDPR Art. 28.
- [`self-hosting.md`](./self-hosting.md) — proxy configuration, env-var
  reference, the deployment template that activates the controls above.
- [`SECURITY.md`](../SECURITY.md) — disclosure policy, response-time
  targets, what's in/out of scope for vulnerability reports.

## Review cadence

This model is reviewed on each significant change to the request path,
the auth surface, or the converter plugin set. The review-trigger items
are flagged in CLAUDE.md under "Network-layer changes quadruple-check"
and "Propagation-Guard an Auth-/Quota-Boundaries".
