### Security — Pillow reads image uploads only in the formats FileMorph supports

`/convert` and `/compress` (and their batch routes) now open uploaded images
with Pillow limited to the formats FileMorph accepts: JPEG (multi-picture
JPEGs from phone cameras included), PNG, WebP, GIF, BMP, TIFF, ICO,
HEIC/HEIF and AVIF. Pillow ships readers for many other formats; they are not
used on these uploads, which keeps the code that parses an uploaded image to
what the service needs. The list is one constant, `IMAGE_INPUT_FORMATS` in
`app/core/image_hardening.py`, and the image converters and compressors open
every upload through `open_image()` there.

An upload none of these readers recognises (a file that isn't an image, one
too damaged to be recognised, or one in another format) now gets `400` with
`X-FileMorph-Error-Code: invalid_input` and "Could not read the image: it is
damaged or not in a supported image format. Save it as PNG or JPEG (e.g. in
an image editor) and try again." A file that isn't an image used to get the
generic `500` ("Conversion failed. …", "Compression failed. …"); damage that
only shows while an image is decoded still does. `/convert/batch` and
`/compress/batch` report the message for the file.

Tests build each supported variant in-process (a two-frame MPO, an animated
PNG, ICO with PNG and with BMP frames, JPEG-compressed TIFF, HEIF and AVIF
among them), check that the list covers every image input the converters and
compressors accept, and check that files in five other Pillow formats are
refused without any reader outside the list being consulted.
