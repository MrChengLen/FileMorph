### Changed — compressing never hands back a larger file: the original comes back without its metadata

A photo from the web or a messenger is often compressed harder already than
the chosen quality, and re-encoding it made it larger (a web JPEG +5 %, a
WebP +13 % at the default quality 85) — offered all the same as
"Download Result". Now, when compressing a JPEG, PNG or WebP would not make
it smaller, the original comes back instead, put together anew from the
parts of the picture: the coded image data is copied as it is, not
re-encoded; EXIF (GPS position, camera), XMP and IPTC (names), comments,
thumbnails, a phone's appended second picture and other parts are left
out (a file with a part the reader can't judge keeps the re-encode); the
colour profile and a photo's orientation stay. The decoded picture is
checked to be unchanged before the file is used.

- The page says so ("At this setting the file would not have got
  smaller …"), titles the note "Your original, without metadata" and labels
  the button "Download the original without metadata"; the size estimate
  under the slider says beforehand that the file would not get smaller.
- In target-size mode the original comes back only if it fits the target —
  rather than a larger quality-95 re-encode that also fits.
- The API marks it with `X-FileMorph-Warnings: original=kept` (per file in
  `X-FileMorph-Batch-Notes` and `manifest.json` for a batch). A turned or
  animated PNG or WebP, TIFF, AVIF and video keep the re-encode.
