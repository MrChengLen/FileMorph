### Fixed — the privacy notice names every right, the Cloudflare transfer and a 30-day log limit

The privacy notice (`/privacy`; the German text is authoritative) was missing
parts of what Art. 13, 20, 21 and 77 GDPR require, and its § 4 — where the
hosting line on the homepage has pointed since the claims correction — did not
say what Cloudflare does with a request. Now:

- **Rights:** access, rectification, erasure, restriction, data portability,
  objection and complaint, each with its article. The right to object stands
  on its own in a highlighted box (Art. 21(4) GDPR) and names the processing
  it covers.
- **Supervisory authority:** the Hamburg Commissioner for Data Protection and
  Freedom of Information, with address and website.
- **§ 4 Hosting and connection:** Hetzner holds what FileMorph stores.
  Cloudflare, Inc. (USA) ends the encrypted connection, so it processes IP
  addresses, request data and — in transit — uploaded and converted files;
  the transfer rests on the EU-U.S. Data Privacy Framework plus the EU
  Standard Contractual Clauses, the legal basis is Art. 6(1)(f) GDPR.
- **Recipients:** Zoho also hosts the operator's mailbox, and rare support
  access by Zoho's Indian group company is covered by the Standard
  Contractual Clauses. Stripe's contracting entity is Stripe Payments Europe,
  Ltd.; paid plans are not offered at present.
- **The rest of Art. 13:** the legal basis for processing uploaded files,
  contact by email, server logs deleted after 30 days at the latest, which
  data is required, no automated decisions, and why there is no data
  protection officer.
- The German text addresses the reader as "du" throughout. § 2i, shown only
  with the redaction add-on, says uploads are temporary files on the server,
  not held in memory only.

`docs/sub-processors.md`, `docs/vendor-security-questionnaire.md`,
`docs/records-of-processing-template.md` and `docs/security-overview.md` name
the same entities and transfer bases; `docs/gdpr-privacy-analysis.md` marks
its April recommendation (Cloudflare R2 storage, the federal BfDI) as
superseded. `tests/test_privacy_notice.py` pins all of it in both languages.
