### Fixed — images just over the size limit get the size-limit message

Converting or compressing an image between one and two times the image size
limit (89 megapixels by default, `FILEMORPH_IMAGE_MAX_MEGAPIXELS`) — a
108-megapixel phone photo, say — returned a `500` with the generic
“Conversion failed” or “Compression failed” instead. Pillow raises a
warning there, which FileMorph turns into an error, but the routes caught only
the error Pillow raises above twice the limit. Both now get the `400` with
`X-FileMorph-Error-Code: decompression_bomb` and the advice to make the image
smaller, on `/convert`, `/compress` and `/pdf/insert`.
