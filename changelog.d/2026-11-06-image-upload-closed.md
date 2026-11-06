### Fixed — a failed image or Word conversion no longer leaves its upload behind on Windows

Image conversions (to another image format, and to PDF, also when an image is
inserted into a PDF), image compressions and Word → TXT now release the
uploaded file however they end; an image is closed completely, including a
file Pillow mapped into memory instead of reading it. When decoding failed, a
cut-off JPEG or a broken Word file for example, the file stayed open until
the request was over. Windows cannot delete an open file, so the request's
temporary folder stayed behind until the next sweep.
