### Changed — the target size is an upper bound

Compressing to a target size no longer accepts a result up to 3 % above it
(5 % for PDFs): `/compress`, `/compress/batch` and `/pdf/compress` now return
the best quality that is at most the target, so the file fits an upload limit
of the same size. When even the lowest quality is too big, an image is scaled
down to fewer pixels, and a PDF's embedded images are scaled down (they keep
their place and size on the page), and the search runs again. The result
stays above the target only when not even an image's smallest size (short
edge 16 px, quality 1) fits — one carrying a large colour profile, say; the
image then keeps its size at quality 1 — or for a PDF whose images can't
shrink enough, for instance because its text and fonts leave too little room.

Every such result says so. `/compress` sends `X-FileMorph-Converged` and, in
`X-FileMorph-Warnings`, `resized=<w>x<h>` or `target=missed`; `/pdf/compress`
sends `scaled=<percent>`. `/compress/batch` lists the files in the new
`X-FileMorph-Batch-Notes` header and in `manifest.json`, which the ZIP now
carries whenever a file has notes; every manifest entry and the body of a 422
gained a `notes` list. The web UI shows the notes next to the result, in
English and German, and reads a size in MB as 1,000,000 bytes, rounded down,
so the result fits a limit of that size however a portal counts it.
`X-FileMorph-Converged` on `/pdf/compress` now means "at most the target": a
PDF with nothing to recompress that already fits reports `true`. The pages,
`llms.txt` and the API docs describe the upper bound instead of the 3 %
overshoot.
