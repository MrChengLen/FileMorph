### Added — a format search on `/formats`, and each conversion listed once

`/formats` has a search field above the list. Type a format, and the page
shows only what works with it:

- a format or file extension ("heic", ".PDF"), another spelling ("jpeg",
  "tif") or another name ("Word", "Excel", "E-Mail", "PDF/A");
- a kind of file ("Foto", "Video", "Musik", "Tabelle"; "iPhone" stands for
  HEIC, HEIF and MOV);
- a pair ("heic to jpg", "heic in jpg", "mp4 → gif", also "convert heic to
  jpg"). For a pair FileMorph can't convert, the page says so and shows
  everything with the first format.

The matching tools come along from a new "Tools" row: a search for "PDF"
also shows the four PDF tools. A line says how many conversions and tools
match. When nothing matches, the page offers to show all formats or to drop
the file into the converter, instead of an empty page. The search is kept in
the link's fragment (`/formats#q=heic`), so such a link can be shared. The
page's address stays the same. Without JavaScript the field is hidden and the
full list shows, as before.

Each conversion is now listed once. The converter also accepts the spellings
JPEG, TIF and HTM, and the list showed them as formats of their own. Three of
those entries weren't conversions at all (JPG to JPEG, TIF to TIFF, TIFF to
TIF). A .jpeg, .tif or .htm file converts as before. The chips now read
"PDF/A", "WebP" and "WebM".

The homepage links the page under its tools: "All formats →".
