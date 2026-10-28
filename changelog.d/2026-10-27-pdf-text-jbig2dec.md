### Fixed — PDF → TXT: a PDF with JBIG2 page content gets a `400`, not a `500`, where `jbig2dec` is installed

On a Linux host that has the `jbig2dec` program installed and runs FileMorph
without root privileges, PDF → TXT answered with a `500` when a PDF's page
content, rather than an image in it, was stored as JBIG2 data. Such a PDF
now gets the usual `400` for an unreadable PDF, as on hosts without the
program. PDFs with JBIG2 images, such as many scans, were not affected, and
neither was the Docker image, which doesn't ship `jbig2dec`.
