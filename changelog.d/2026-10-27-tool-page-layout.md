### Changed — the tool pages share one layout, with a breadcrumb instead of "← Back"

- Every tool page (the conversion pages, the PDF tools, `/compress` and
  `/redact`) now shows where it sits, "Tools › <the tool's name>", instead of a
  "← Back" link. That link led to the homepage on some pages and to `/formats`
  on others, although most visitors arrive from a search.
- The related block at the end of the conversion pages, the PDF tools and
  `/compress` now lists the tool's neighbours under their `/tools` names, then
  "All tools →" and "Use it via the API ↗", which opens the API documentation.
  The PDF tools still link each other.
- The three page types render from one template
  (`app/templates/layouts/tool_page.html`). Their titles, descriptions,
  headings and FAQ questions are unchanged, which
  `tests/golden/page_texts.json` confirms.
