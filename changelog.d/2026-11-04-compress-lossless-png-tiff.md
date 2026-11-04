### Fixed — TIFF compression packs losslessly instead of saving raw pixels, and PNG/TIFF lose a slider that did nothing

Compression saved a TIFF without any compression, as raw pixels, so an LZW or
Deflate TIFF came back larger (7.4 MB became 11.5 MB). It is now packed
losslessly with Deflate and the horizontal predictor that photo TIFFs from
Photoshop, GIMP or libvips use — such an LZW TIFF of 1.6 MB comes back at
1.4 MB. Black and white gets the smaller of Group 4 and Deflate. A TIFF that
stores JPEG data inside can still come out larger.

PNG and TIFF come out the same whatever the quality — PNG was always packed
at zlib's highest level — so in Compress mode the quality slider hides for
them, and a note says what does make them smaller: WebP or JPG, with a switch
that converts the one file to WebP.

- The `/compress` page, `/formats`, the API docs and the message for
  `target_size_kb` on another format no longer say that `quality` shrinks PNG
  or TIFF; that message now fits video too.
- Only the first page of a multi-page TIFF is compressed; `docs/formats.md`
  now says so.
