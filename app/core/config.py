# SPDX-License-Identifier: AGPL-3.0-or-later
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.compat import data_dir


def _default_keys_file() -> str:
    return str(data_dir() / "api_keys.json")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = False
    app_version: str = "1.1.0"

    api_keys_file: str = ""  # resolved below if empty

    max_upload_size_mb: int = 100

    cors_origins: str = "http://localhost:8000"
    jwt_secret: str = "dev-secret-change-me-min-32-chars-long"

    # PR-J: RFC 7519 §4.1.1 (iss) + §4.1.3 (aud) claims. Every token this
    # deployment mints carries ``iss=jwt_issuer`` and ``aud=jwt_audience``;
    # every decode path validates them. Defense-in-depth: a token minted by
    # a *different* FileMorph deployment (or another service that happens to
    # share a leaked secret) is rejected even if the HMAC checks out,
    # because the audience/issuer won't match. The defaults are
    # deployment-agnostic; a multi-tenant operator running several FileMorph
    # instances behind one identity provider gives each a distinct
    # ``JWT_AUDIENCE`` so a token scoped to instance A can't be replayed
    # against instance B. Changing either value invalidates all in-flight
    # tokens on the next request (same blast radius as rotating JWT_SECRET).
    jwt_issuer: str = "filemorph"
    jwt_audience: str = "filemorph-api"

    # Stripe (leave empty to disable billing)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_pro_price_id: str = ""
    stripe_business_price_id: str = ""

    # Whether to expose /pricing — independent of Stripe availability so the
    # SaaS deployment can run a "Coming Soon" pricing page during the window
    # between launch and Stripe live-mode activation. Self-hosters default
    # to off (no commercial offer to advertise).
    pricing_page_enabled: bool = False

    # Displayed prices (deployment-agnostic). These are DISPLAY-ONLY strings
    # surfaced on /pricing + /enterprise via app/core/pricing.py — the Stripe
    # price IDs above remain the source of truth for the actual charge. Empty
    # by default so a self-hoster who flips PRICING_PAGE_ENABLED on does NOT
    # inherit filemorph.io's amounts; the tiers then render without a price
    # ("Contact us"). filemorph.io sets these in its own deployment env.
    # Plain numbers, no currency symbol (the € is rendered by the template).
    price_currency: str = "EUR"
    price_pro_display: str = ""
    price_business_display: str = ""
    price_compliance_starter_display: str = ""
    price_compliance_standard_display: str = ""
    price_compliance_enterprise_display: str = ""

    # S10-lite analytics: per-day counter increments for page views,
    # conversions, registrations, failures. Default on — the counters are
    # aggregates only, no personal data, no cookie-banner implication.
    # Self-hosters who don't want the table populated can set this false;
    # the cockpit then renders an empty-state notice.
    metrics_enabled: bool = True

    # Compliance-Edition audit log (NEU-B.1). When false, ``record_event``
    # is fire-and-forget — failures get logged at WARNING and the request
    # path is unaffected. When true (Compliance Edition default; opt-in
    # for any deployment that needs ISO 27001 A.12.4.1 / BORA §50 /
    # BeurkG §39a compliance), a failed audit write raises
    # AuditWriteError and the calling route refuses to serve a result it
    # could not log. Self-hosters set ``AUDIT_FAIL_CLOSED=true`` in
    # their environment when they need the strict mode.
    audit_fail_closed: bool = False

    # NEU-B.2 retention policy. The Cloud edition runs strict
    # zero-retention by design — every convert/compress flushes its temp
    # dir in a ``finally`` block, and there is no S3/R2 storage layer
    # active. ``retention_hours`` is therefore an informational knob
    # surfaced to self-hosters: it documents the operator's declared
    # retention window for any future storage-key-backed pipeline (the
    # ``FileJob.expires_at`` column is reserved for exactly this) and
    # is recorded into audit-event payloads where applicable. Default 0
    # means "ephemeral by design" and matches the Cloud-edition privacy
    # statement; Compliance-edition self-hosters who need a non-zero
    # retention window for eDiscovery/GoBD workflows set this to the
    # value their own privacy policy declares.
    retention_hours: int = 0

    # Background sweep cadence for orphaned ``fm_*`` temp dirs. The
    # request path already cleans up its own temp dir in a ``finally``
    # block; this sweep only catches crash-recovery cases where a worker
    # was killed mid-conversion. A startup sweep covers process-restart
    # crashes; the periodic sweep covers long-running processes that
    # stay up across many incidents. Set to 0 to disable the periodic
    # sweep entirely (the startup sweep still runs).
    temp_sweep_interval_minutes: int = 60

    # How old a temp dir must be before the sweep removes it. Smaller
    # than the longest plausible single conversion (xlsx-on-low-CPU can
    # take ~30 s; video conversions can run minutes). 10 minutes leaves
    # a wide safety margin while still cleaning up promptly after a
    # crash. Compliance-edition operators who run very long batch
    # pipelines can raise this to match their longest job.
    temp_sweep_max_age_minutes: int = 10

    # NEU-D.1 capacity guard. The pricing page advertises monthly
    # call quotas (10k Pro / 100k Business); without a parallelism
    # cap a single 25-file batch can OOM the worker on a 4 GB box.
    # The semaphore in app/core/concurrency.py enforces a global
    # cap and a per-actor cap on /convert + /compress. These three
    # knobs let the operator tune for the actual host:
    #
    # - max_global_concurrency: total parallel slots. Default 4 is
    #   sized for a 4 GB host with the existing per-tier output
    #   caps; raise to ~CPU-count on a bigger box.
    # - concurrency_acquire_timeout_seconds: how long a request
    #   waits before giving up on a slot. Small enough that callers
    #   fail fast under saturation, big enough to absorb the
    #   sub-second jitter of two requests racing for the same slot.
    # - concurrency_retry_after_seconds: value sent in the
    #   ``Retry-After`` header when the slot is denied. Doubling as
    #   the documentation contract for the rate-limited response.
    max_global_concurrency: int = 4
    concurrency_acquire_timeout_seconds: float = 0.5
    concurrency_retry_after_seconds: int = 5

    # Transactional email (leave smtp_host empty to disable sending — dev mode)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "FileMorph"
    smtp_reply_to: str = ""

    # Recipient inbox for the public /contact form. Falls back at the
    # use-site to smtp_reply_to, then smtp_from_email. Empty everywhere →
    # the form still renders but submissions are logged and dropped (same
    # no-op-when-unconfigured behaviour as transactional email when
    # smtp_host is empty).
    contact_form_recipient_email: str = ""

    # Public base URL used when building links in outbound emails.
    app_base_url: str = "http://localhost:8000"

    # Default UI locale for visitors with no signal (no cookie, no
    # Accept-Language match, no URL prefix). FileMorph upstream defaults
    # to ``de`` (Hamburg-based operator, German tax registration). A
    # self-hoster targeting an EN-first audience can flip this with
    # ``LANG_DEFAULT=en`` in the deployment env without touching code.
    # Supported values: ``de``, ``en``.
    lang_default: str = "de"

    # Contact for security disclosures (referenced from /.well-known/security.txt
    # per RFC 9116). Self-hosters should override this to their own org's
    # security alias; the default value points at the upstream project so even
    # an unconfigured deployment is reachable rather than silently broken.
    security_contact_email: str = "security@filemorph.io"

    # Optional cross-origin base for heavy upload POSTs (convert/compress,
    # single + batch). Empty string keeps uploads same-origin — the only
    # reason to set this is when the main site sits behind a proxy that
    # caps request bodies (e.g. Cloudflare Free at 100 MB) and uploads
    # need to bypass it via a separate tunnel subdomain like
    # `https://api.example.com`. All non-upload API calls (formats, auth,
    # billing) stay same-origin regardless.
    api_base_url: str = ""

    # DOCX → PDF engine selection. The pure-Python pipeline
    # (mammoth + WeasyPrint) is fast and ships in every image but cannot
    # round-trip footnotes, headers/footers, multi-level numbering, TOC
    # fields, section page-setup, or OLE objects — exactly the elements
    # Behörden / Kanzleien / Klinik-Word-Docs depend on. The high-fidelity
    # path delegates to LibreOffice (``soffice --headless --convert-to pdf``)
    # which preserves all of those.
    #
    # Values:
    #   - ``auto`` (default): probe each DOCX for complex features
    #     (footnotes, headers/footers, multi-section, OLE); simple docs
    #     stay on mammoth+WeasyPrint, complex docs route to LibreOffice
    #     *if* ``soffice`` is on PATH, else fall back to mammoth and emit
    #     ``X-FileMorph-Warnings: engine=mammoth_fallback,…``.
    #   - ``libreoffice``: always use LibreOffice (errors at convert time
    #     if ``soffice`` is not on PATH). Recommended setting in the
    #     ``filemorph:office`` image variant.
    #   - ``mammoth``: always use the pure-Python path; never invoke
    #     LibreOffice. Recommended for self-hosters who run the slim image
    #     and explicitly accept the fidelity ceiling for predictability.
    office_engine: str = "auto"

    # Hard upper bound on how long a single ``soffice --convert-to`` call
    # may run before we kill it. 60 s is comfortable for a 100-page Word
    # report on a 4 GB host; raise on bigger boxes if you regularly
    # convert long forms. Ignored when ``office_engine=mammoth``.
    office_subprocess_timeout_seconds: int = 60

    # AI File Operations (Enterprise Edition — app/ee/, commercial-only; see
    # app/ee/README.md). Inert unless ai_operations_enabled is set — the same
    # "inert without env vars" pattern as Stripe/SMTP/audit. This is a
    # paid-only add-on for the hosted service, NOT an AGPL engine feature.
    #
    # Margin-opacity: the only cost-revealing knob is ai_credit_cost_redact,
    # and it lives HERE (env), never in source. Clients and the repo see only
    # "credits" — never a model id, token count, or euro cost. filemorph.io
    # sets the real cost in its private deployment env; the default below is a
    # neutral unit, not the production figure.
    ai_operations_enabled: bool = False
    # Comma-separated tiers allowed to call AI operations (paid-only gate).
    ai_eligible_tiers: str = "pro,business,enterprise"
    # Credits charged per redaction apply. Env-driven so the margin stays opaque.
    ai_credit_cost_redact: int = 1

    def model_post_init(self, __context) -> None:
        if not self.api_keys_file:
            self.api_keys_file = _default_keys_file()

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def cors_origins_list(self) -> list[str]:
        if self.cors_origins == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",")]

    @property
    def ai_eligible_tiers_list(self) -> list[str]:
        return [t.strip() for t in self.ai_eligible_tiers.split(",") if t.strip()]


settings = Settings()
