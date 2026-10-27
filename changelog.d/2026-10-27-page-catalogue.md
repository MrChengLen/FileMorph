### Changed — one catalogue of public pages feeds the sitemap and `/llms.txt`

`app/core/catalog.py` lists every public page a visitor lands on once, in
display order: its path, its sitemap priority, the switch that gates it and
its `/llms.txt` line. The sitemap, `/llms.txt`, the page routes' whitelist and
the "Related tools" links of the PDF tool pages are now built from it; each
used to keep its own hand-written list. Both files list the same pages as
before, now in the catalogue's order: the PDF tools and the "… to PDF"
conversions first, then the image tools.

New tests in `tests/test_catalog.py` check that every catalogued page renders,
that every public page route is catalogued, that the sitemap and `/llms.txt`
match the catalogue, that no internal link leads to an error page, and that
titles and meta descriptions fit a search snippet. The titles, meta
descriptions and headings of the homepage, `/tools` and the tool pages are
pinned in `tests/golden/page_texts.json`; after a deliberate change, rerun the
test with `FILEMORPH_UPDATE_GOLDEN=1` and commit the file.
