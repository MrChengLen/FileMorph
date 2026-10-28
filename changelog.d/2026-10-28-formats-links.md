### Added — every conversion on `/formats` is a link

`/formats` lists every conversion FileMorph supports, and each one is now a
link. Where a conversion has a page of its own (the curated pairs, and
Video to GIF for every video format), the link goes there.

Every other link opens the converter on the homepage, pre-set to that
conversion:

- a note above the drop field names the conversion and the file to choose;
- the file picker offers only that format;
- "Convert something else" goes back to the plain converter.

The preset travels in the link's fragment (`/#convert=xlsx-to-csv`). A
fragment never reaches the server, so no new pages appear for search
engines. The preset only takes effect for a conversion the instance
supports.
