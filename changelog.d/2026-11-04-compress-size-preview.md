### Added — the compress slider shows the result's size before the upload (one JPEG)

With one JPEG in Compress mode, the line under the quality slider says how
large the result will be — "Estimated size: about 882.8 KB", above "42%
smaller than the original · worked out in your browser, nothing uploaded" —
and follows the slider. The browser encodes the picture itself; nothing goes
to the server until Compress is pressed.

- The number is the server's own: the server re-encodes a JPEG with
  libjpeg-turbo, and Chromium's canvas encoder is the same libjpeg-turbo, so
  its file differs only in its header segments. A 64 × 64 probe picture
  proves that at the chosen quality first. Checked byte for byte against the
  server on JPEGs with an EXIF orientation, a colour profile (sRGB and wide
  gamut), progressive and 4:4:4 originals.
- Where the probe doesn't match — Safari and Firefox encode differently, and
  Chromium switches to 4:4:4 at quality 100 — the line says so and points to
  "By target size"; so it does for WebP and AVIF, greyscale and CMYK JPEGs,
  and pictures over 16 megapixels (25 on devices with 8 GB or more). For a
  video it says the size is known only after compressing.
- A quality that would make the file larger than the original turns the line
  amber: "32% larger than the original — choose a lower quality".
