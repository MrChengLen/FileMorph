### Security — three DOMPurify advisories in the Swagger UI bundle accepted until 2026-11-02

Three DOMPurify advisories published on 2026-10-22 hit the copy bundled in
Swagger UI 5.33.1, which renders the API explorer on `/docs`:
GHSA-cg2g-xh64-v4q7 (critical), GHSA-mrv2-3pqr-j5jr (high) and
GHSA-c6gr-qvv4-5v3f (low). Each needs a DOMPurify option that Swagger UI does
not set (`SAFE_FOR_TEMPLATES` with DOM output, the `IN_PLACE` mode, the XHTML
parser), and the page renders only FileMorph's own OpenAPI schema. The fix,
DOMPurify 3.4.17, is in no Swagger UI release yet: 5.34.0 still bundles 3.4.16.
`scripts/check_vendor_advisories.py` therefore accepts the three until
2026-11-02, the date of the planned Swagger UI update, when they are decided
again. `docs/security-overview.md` lists them with the two accepted on
2026-10-20.
