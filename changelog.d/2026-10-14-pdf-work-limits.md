### Changed — PDF tools: page selections count each page once; split stops at the output cap

- **Page selections** (`/pdf/extract`): a page selected twice now counts
  once against the 10 000-page cap. `1-10000,1-5` used to be refused with
  "You can extract at most 10,000 pages at once", although it selects
  10 000 pages. Overlapping and adjacent ranges are merged before pages are
  counted. A selection longer than 65 536 characters gets
  `400` with `invalid_page_selection` and "The page selection is too long.
  Use ranges such as 1-100 instead of listing pages one by one." (every
  page up to the cap, listed one by one, is about 49 000 characters).
- **Split** (`/pdf/split`) checks the tier output cap while it writes the
  single-page PDFs and stops with the usual `413` (`output_cap_exceeded`,
  "Output too large (over the N MB cap).") once they pass it. Each single-page PDF carries its own copy of the
  images and fonts it uses, so a split can come out larger than its input.

Tests cover repeated and adjacent ranges, a selection exactly at and just
over the length limit, and a split stopping at the cap while it writes.
