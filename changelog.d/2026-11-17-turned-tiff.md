### Fixed — a turned TIFF no longer comes out scrambled

An uncompressed TIFF saved in one piece (one strip or tile, as Pillow and
some other programs write it) whose page is stored on its side and turned
upright by its orientation tag (a quarter turn), in greyscale, palette, RGBA,
CMYK or 16-bit, came out scrambled from every image path: compressing,
converting, TIFF → PDF and "Insert pages". Pillow 13.0 memory-maps such an
uploaded file at its turned size instead of its stored one
(python-pillow/Pillow#10220, fixed after 13.0). FileMorph now has Pillow read
the pixels of an upload instead of mapping it, and a later page of such a TIFF
gets the same size check as every other page. Black-and-white and RGB pages,
and TIFFs saved in several strips as scanners usually write them, were not
affected.
