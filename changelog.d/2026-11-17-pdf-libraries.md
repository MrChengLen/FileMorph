### Security — pypdf 7.1.0 and pikepdf 10.18.1

pypdf, which FileMorph uses to split PDFs, extract and insert pages, turn PDFs
into text and size the page of an image → PDF, moves from 6.21.4 to 7.1.0.
pypdf lists five changes in 7.0.0 and 7.0.1 as security fixes; no advisories
were published for them as of 2026-11-17. One applies to every PDF FileMorph
reads with pypdf: an object stream whose offsets do not strictly increase is
refused, and such a PDF now gets the "could not read" message. The other four
concern pypdf functions FileMorph does not use: reading XFA forms, two in
image handling, and the file identifier pypdf writes when it encrypts a PDF.

pypdf 7 is a new major version. It removes the functions deprecated in 6.x,
none of which FileMorph calls, and needs cryptography 43 or newer (the image
ships 50.0.2). It no longer decodes streams that use the short filter names
meant for inline images, such as `/Fl` for `/FlateDecode`, which pypdf 6 still
decoded. Where such a stream has to be decoded (always for PDF → TXT; for the
page tools when it holds the document's objects), the PDF now gets the "could
not read" message. Such PDFs are rare. Two more kinds of damaged PDF get that
message too, instead of a generic error. Text extraction is faster for
left-to-right text and on pages drawn only with vector graphics.

pikepdf, which compresses PDFs and writes PDF/A, moves from 10.17.0 to 10.18.1.
It also fixes a crash on certain malformed JBIG2 images, which are now treated
as images that cannot be decoded. pikepdf 10.18 refuses to put objects of one
document into another. PDF compression did that when it decoded a JPEG behind
a lossless filter that has filter parameters; it now takes the parameters from
its own copy, so such images are still recompressed. The qpdf library bundled
in the wheels stays at 12.4.2.
