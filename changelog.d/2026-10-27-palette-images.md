### Fixed — palette images (GIF, 8-bit PNG) keep their colours

Since metadata stripping became the default in 1.1.0, converting a palette
image — every GIF, palette (8-bit) PNGs, indexed BMP and TIFF files — to PNG,
WebP, AVIF, GIF, BMP, TIFF or ICO, or compressing one, returned a broken image:
one colour for every pixel, and for BMP a file that wouldn't open. The
stripping copied the pixels, which in a palette image are indices into its
colour table, but not the table, and it dropped which colour is transparent.
Both are kept now; EXIF, XMP and IPTC are still removed. A palette PNG with an
alpha table, as pngquant and TinyPNG write them, keeps its transparent areas
when converted to GIF, and a PNG with one transparent colour keeps it when
compressed. JPEG and PDF output were not affected.
