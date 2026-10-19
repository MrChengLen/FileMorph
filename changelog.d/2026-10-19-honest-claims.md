### Fixed — public pages, catalogs and docs say only what the code does

Several claims had drifted from the code, each on many surfaces at once:
the pages and both translation catalogs, `/llms.txt`, the JSON-LD, the
content modules, `README.md`, the docs and `.env.example`. Each kind of
claim is now fixed everywhere and pinned by `tests/test_public_claims.py`.

- **No DPA for self-hosting.** `/enterprise`, `/pricing` and the homepage
  promised a "signed DPA" for the self-hosted Compliance Edition, and the
  pricing table ticked the DPA only in the self-hosted column (that row is
  gone; whether a hosted plan needs one is still open). When customers
  run FileMorph on their own servers, we process no data on their behalf, so
  no DPA is needed — as `docs/dpa-template.md` §1 already said. The pages,
  README, `COMMERCIAL-LICENSE.md`, the onboarding guide and the vendor
  questionnaire now say so; the contract templates themselves are unchanged.
- **Audit-log norms.** Citations now use ISO/IEC 27001:2022 — A.8.15 for the
  audit log instead of A.12.4.1, and the 2022 numbers for the auth events,
  release signing and metadata stripping. § 39a BeurkG is gone (it concerns
  electronic certifications), and so is the "BORA §50" reference until counsel
  confirms § 50 BRAO applies. The German pages translated "tamper-evident" as
  "manipulationssicher" (tamper-proof); the chain detects edits, so it now
  reads "manipulationserkennbar".
- **Target size.** No longer called "exact" and no "±3 %": a result is
  accepted up to 3 % above the target (`tolerance=0.03`), so a 5 MB target
  can give 5.15 MB — and an image that can't get that small comes back as
  small as it gets. The homepage FAQ, `/formats`, `/compress`, `/tools`, the
  tool's target-size field, `/llms.txt` and the JSON-LD say so, and the
  homepage comparison no longer calls target-size compression "rare".
- **Hosting.** Every page that says where filemorph.io runs uses one
  sentence — server at Hetzner in the EU, connections via Cloudflare (USA) —
  linked to § 4 of the privacy policy (new anchor `#hosting`), shown only
  where the commercial pages are on (`PRICING_PAGE_ENABLED`), so a
  self-hosted instance doesn't claim filemorph.io's hosting. Meta
  descriptions, the JSON-LD and the social-preview image, which can't carry
  the link, no longer make a hosting claim; the privacy policy's redaction
  section says that uploads travel through Cloudflare like every request.
- **`/compress`** no longer says "in your browser": the files are processed on
  the server.
- **Pricing.** The audit log and signed releases are ticked for every plan.
  No plan shows more parallel requests than the server's shared pool runs at
  once (`MAX_GLOBAL_CONCURRENCY` — Business showed 6), and "10 req/min" is no
  longer listed as a plan feature: the per-minute limit is the same for every
  plan. "Free tier is live today" and "Pro & Business launch shortly" became
  "Paid plans are currently not available".
- **Smaller fixes.** The privacy policy no longer says usage is shown in the
  dashboard (there is no counter); design partners give an anonymised case
  study instead of a logo mention; `/enterprise` says the document and
  spreadsheet share of its "180+ format pairs" (13); and
  `docs/gdpr-privacy-analysis.md` no longer describes a self-service data
  export or email change — both go through privacy@filemorph.io.
- **Contrast.** The "processed server-side" note on the homepage and the
  conversion pages, and the tool's format and target-size hints, were
  about 1.95–2.5 : 1 against the page; they now use the `ink-muted` token
  (about 7.9 : 1, WCAG AA).
