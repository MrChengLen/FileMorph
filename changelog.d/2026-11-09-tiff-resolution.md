### Fixed — a fax keeps its proportions: images keep their resolution

A fax in normal mode is scanned at 204 dpi across and only 98 down; its
resolution is what says that its pixels are twice as tall as wide. TIFF →
PDF and "Insert pages" made every page 150 dpi each way, so such a fax page
came out on its side and squashed (11.5 × 7.2 inches instead of a letter
page), and compressing or converting an image dropped the resolution with
the rest of the metadata. Now a TIFF page becomes a PDF page of the size its
resolution gives it — each page of a multi-page TIFF its own, so a fax that
mixes normal and fine pages comes out right too — and PNG, JPEG, TIFF and
BMP results keep the resolution, compressed or converted.

- The resolution is picture geometry, not personal data: it says how large
  the picture is on paper. It is swapped when a picture is turned by a
  quarter, and drops with the pixels when target-size compression scales an
  image down, so the page keeps its size.
- Any other picture still becomes a 150-dpi PDF page — a camera's 72 dpi is
  a default, not a size — and a TIFF without a resolution too. A value below
  10 or above 10 000 dpi is no measurement and is dropped, and a PDF page
  that would be larger than 200 inches a side (what Acrobat shows) is made
  smaller, keeping its proportions.
- When compressing hands back the original instead (`original=kept`), a
  JPEG keeps the resolution in its JFIF header; one held only in its EXIF
  block goes with the block.
