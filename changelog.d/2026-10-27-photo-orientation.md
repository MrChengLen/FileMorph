### Fixed — portrait photos stay upright

A photo taken upright on a phone came back lying on its side when converted
(to PNG, JPG, WebP and the other image formats), compressed or turned into a
PDF. Phones store the picture as the sensor saw it and note the turn in the
photo's EXIF data; the metadata stripping removed that note without applying
it. The turn now goes into the pixels before the EXIF is removed, for all
eight EXIF orientations (and for a turn noted only in XMP). HEIC photos and
TIFF files were not affected: their decoders already turn the picture. AVIF
files with a rotation were affected too and are fixed as well. A photo whose
EXIF block can't be read stays as stored, as before.
