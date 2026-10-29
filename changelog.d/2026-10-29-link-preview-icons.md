### Changed — a shared link previews the page it points to

A link to a FileMorph page in a messenger or on a social network (WhatsApp,
Signal, Slack, LinkedIn, iMessage, Mastodon) used to preview as "FileMorph"
with the same generic line on every page. The preview now carries the page's
own title and description, for example "PDF-Seiten einfügen oder anhängen —
kostenlos"; the name FileMorph moves to `og:site_name`.

- An iPhone or iPad that adds a page to its home screen shows the FileMorph
  logo (180 × 180 px) instead of a screenshot of the page.
- `/apple-touch-icon.png` and `/favicon.ico` answer at the root, where clients
  look for them on their own, instead of rendering the 404 page. They don't
  count as page views.
- The web manifest lists 192 and 512 px PNG icons, one of them maskable, for
  Android home screens.
