### Fixed — the privacy notice names every right, the Cloudflare transfer and a 30-day log limit

The privacy notice (`/privacy`; the German text is authoritative) was missing
parts of what Art. 13, 20, 21 and 77 GDPR require, and its § 4 — where the
hosting line on the homepage has pointed since the claims correction — did not
say what Cloudflare does with a request. Now:

- **Rights:** access, rectification, erasure, restriction, data portability,
  objection and complaint, each with its article. The right to object stands
  on its own in a highlighted box (Art. 21(4) GDPR) and names the processing
  it covers. Requests are answered without undue delay, within one month
  (Art. 12(3)).
- **Supervisory authority:** the Hamburg Commissioner for Data Protection and
  Freedom of Information, with address and website; a complaint can also go
  where the reader lives or works or where the infringement took place.
- **§ 4 Hosting and connection:** Hetzner holds what FileMorph stores.
  Cloudflare, Inc. (USA) ends the encrypted connection, so it processes IP
  addresses, request data and — in transit — uploaded and converted files.
  The transfer rests on Cloudflare's EU-U.S. Data Privacy Framework
  certification (adequacy decision); the Standard Contractual Clauses in its
  DPA apply only if that lapses. Legal basis: Art. 6(1)(f) GDPR.
- **Recipients:** Zoho Corporation GmbH, the contracting entity for Germany,
  sends account emails and hosts the operator's mailbox; rare support access
  by Zoho's Indian group company is covered by the Standard Contractual
  Clauses. Stripe's contracting entity is Stripe Payments Europe, Ltd.; Stripe
  and Cloudflare process part of the data under their own responsibility;
  paid plans are not offered at present. A copy of the Standard Contractual
  Clauses is available on request.
- **The rest of Art. 13:** the legal basis for processing uploaded files
  (Art. 6(1)(b), and (f) for other people's data in a file) and for statutory
  retention (Art. 6(1)(c)), contact by email, server logs deleted after 30
  days at the latest, which data is required, no automated decisions, and why
  there is no data protection officer.
- § 2a no longer says no file content is "stored in any form": uploads sit
  on the server as temporary files while processed, and the audit log keeps
  the output's hash. § 6 names Cloudflare's `cf_clearance` cookie after a
  security check. The notice says it applies to filemorph.io; a self-hosted
  instance needs its own.
- The German text addresses the reader as "du" throughout and cites
  "Art. 6 Abs. 1 lit. …". § 2i, shown only with the redaction add-on, says
  uploads are temporary files on the server, not held in memory only.

`docs/sub-processors.md`, `docs/vendor-security-questionnaire.md`,
`docs/records-of-processing-template.md` and `docs/security-overview.md` name
the same entities and transfer bases. Like § 6, `docs/sub-processors.md`,
`docs/vendor-security-questionnaire.md` and `docs/dpa-tom-annex.md` no longer
say "no third-party CDN": the pages load nothing from another domain, but
on filemorph.io every request passes through Cloudflare.
`docs/gdpr-privacy-analysis.md` marks its April recommendation (Cloudflare
R2 storage, the federal BfDI) as superseded. `tests/test_privacy_notice.py`
pins all of it in both languages.
