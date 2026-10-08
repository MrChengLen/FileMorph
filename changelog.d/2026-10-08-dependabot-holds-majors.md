### Changed — Dependabot no longer proposes the WeasyPrint 70 and Stripe 16 majors before their ports

Both majors need code changes first: WeasyPrint 70 reworks the `url_fetcher`
interface that the SSRF guard relies on, and Stripe 16 rejects a parameter the
Checkout call sends. Until now they arrived as pull requests of their own that
could only sit red until someone ported the code. Dependabot now ignores those
version ranges, like the existing caps for pikepdf and the SBOM generator, and
the port itself lifts the cap in `requirements.txt` together with the entry in
`.github/dependabot.yml`. Patch and minor releases below the caps now come in
the weekly batch instead of as pull requests of their own. A new test fails
when an ignore entry outlives its cap, so a lifted cap cannot leave the
package frozen.
