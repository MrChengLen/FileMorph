### Security — CI checks the vendored browser code for known vulnerabilities

pip-audit and Dependabot do not see the browser code vendored under
`app/static/vendor/` (Swagger UI, Chart.js). A new CI step,
`scripts/check_vendor_advisories.py`, asks the OSV advisory database about every
package and version in `app/static/vendor/manifest.json`, plus the libraries a
file's new `bundles` field names (today DOMPurify inside the Swagger UI bundle),
and blocks the build on a finding, the same way pip-audit does. A finding passes
only when it is accepted for that version with a reason and a review date, and
it fails again once that date has passed; an OSV answer that is incomplete or
unreadable fails the step instead of passing it. The weekly `deps-latest`
workflow runs the same check. The two low-severity advisories in the DOMPurify
bundled with Swagger UI 5.33.1 are accepted until 2026-11-02, when the Swagger
UI release that fixes them is two weeks old.
