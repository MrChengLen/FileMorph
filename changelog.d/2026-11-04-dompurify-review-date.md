### Security — five DOMPurify advisories in the Swagger UI bundle accepted until 2026-11-16

Five DOMPurify advisories hit the copy bundled in Swagger UI 5.33.1, which
renders the API explorer on `/docs`: GHSA-cg2g-xh64-v4q7 (critical),
GHSA-mrv2-3pqr-j5jr (high), GHSA-c6gr-qvv4-5v3f, GHSA-6688-9rhm-gjv2 and
GHSA-p98j-92pf-mc4p (low). They stay accepted until 2026-11-16 instead of
2026-11-02, because each still needs a DOMPurify mode or option that Swagger UI
does not use. The Swagger UI update goes straight to 5.34.1 (published
2026-10-30), which bundles the fixed DOMPurify 3.4.17 and so fixes all five,
once it is two weeks old on 2026-11-13; 5.34.0 would have fixed only two of
them. `docs/security-overview.md` lists the new dates.
