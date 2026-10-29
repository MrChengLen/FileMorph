### Fixed — scripts and stylesheets are current right after an update

Pages now link every script and stylesheet with a version taken from the
file's content (`/static/js/app.js?v=<hash>`). After an update, the first
page a browser opens loads the new files. Before, a browser could keep the
previous release's scripts for a while, so a new page could meet code that
did not know it yet — a pre-set conversion link from `/formats`, for
example, would open the plain converter. The app asked browsers to check
scripts again after 5 minutes, but a CDN in front may stretch that
(Cloudflare's default makes it 4 hours).

A request that names the file's current version is cached for a year
(`immutable`), so returning visitors no longer re-check unchanged files. A
request naming any other version is not cached at all, and one without a
version keeps the 5-minute revalidation. If a CDN or cache sits in front of
your instance, it must keep the query string in its cache key — the default
for Cloudflare, Fastly and nginx (see "A cache or CDN in front" in
`docs/self-hosting.md`).
