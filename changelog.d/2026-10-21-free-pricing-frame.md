### Changed — FileMorph is free: the pricing page, navigation and account texts say so

Without Stripe configured no plan can be booked, so `/pricing` no longer shows
Pro and Business as "currently not available". It shows what is free instead:
our server with fair limits (without an account up to 30 MB per file; with a
free account up to 100 MB, 10 files per request and an API key with 1,000
calls a month), self-hosting with no feature gates, and the Compliance Edition for
organizations. A short FAQ says there are no paid plans and that a change would
be announced in advance. The homepage's plan teaser becomes the same free
summary, and its FAQ no longer mentions paid hosted plans. A deployment with
Stripe configured keeps the plan cards, the comparison table and the checkout
unchanged.

- Navigation: "Self-Hosted" is now "Self-host" ("Selbst hosten"), "Enterprise"
  is "For organizations" ("Für Organisationen"), and "Register" is no longer in
  the main navigation; registering stays reachable from the login page, the
  pricing page and the developer teaser. The URLs are unchanged.
- The registration page no longer promises an upgrade path: a free account is
  for an API key and larger files.
- Terms § 8: without Stripe, a sentence says that no paid plans are offered and
  that § 8 and § 9 apply only once they are.
- `/enterprise`: the per-year price note only appears when a tier shows a price;
  with no display price configured every tier reads "on request".
- README and `COMMERCIAL-LICENSE.md`: the hosted service is described as free
  (no Pro/Business rows), and the Compliance Edition tiers are priced on request.
