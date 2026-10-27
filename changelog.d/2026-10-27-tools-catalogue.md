### Changed — `/tools` lists every tool page, grouped by file type; one name per tool

- `/tools` now has a card for each of the 16 tool pages, including the 12
  conversion pages it did not list before. The cards are grouped into "PDF
  tools" and "Images" with jump links, and each one says that the tool runs on
  the server. The "Convert & compress files" card became a line pointing to the
  converter on the homepage, which still takes any file and converts several
  at once.
- Each tool carries one name on the homepage's quick actions, on `/tools` and
  in the footer's "Tools" group. The target-size compressor is "Compress image (KB/MB)"
  everywhere (it was also "Compress to a target size" and "Compress to size"),
  and the redaction add-on is "Redact PII" (its card says the download is
  paid; which plans may download is configurable).
- The quick actions, the `/tools` cards and the footer's "Tools" group and
  "Popular conversions" grid now come from the page catalogue
  (`app/core/catalog.py`), so a new tool page needs only its catalogue entry
  to show up there. The
  footer lists follow the catalogue's order: PDF tools first, then images;
  the "Popular conversions" grid keeps its "JPG → PDF" link names for now.
