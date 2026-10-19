### Changed — PDF compression leaves JPEG 2000 images as they are

PDF compress-to-target (`/api/v1/pdf/compress`) re-encodes embedded images
stored as JPEG (`/DCTDecode`, also behind a lossless filter such as ASCII85 or
Flate, as ReportLab writes them) or with the lossless filters qpdf decodes
itself (Flate, LZW, run-length, ASCII85, ASCIIHex). JPEG 2000 images now stay
as they are, and so do images over the image size limit
(`FILEMORPH_IMAGE_MAX_MEGAPIXELS`, 89 megapixels by default) and images with
longer filter chains. An image that can't be read is skipped instead of
failing the request. A losslessly stored image with a `/Decode` array (e.g.
inverted grayscale) keeps its look; it used to come out inverted.

Tests compress PDFs with a JPEG 2000 image, unreadable and damaged images, a
JPEG of another size than its dictionary declares, a doubly compressed image
and a malformed filter, each next to an ordinary JPEG, and check that only the
ordinary JPEG is re-encoded; that images over the size limit stay as they
are; that a losslessly stored image and JPEGs behind ASCII85 and Flate are
re-encoded; and that an inverted grayscale image keeps its look.
