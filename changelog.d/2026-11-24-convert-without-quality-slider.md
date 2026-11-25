### Changed — converting has no quality slider; Compress makes a result smaller

Converting in the web UI no longer shows a quality slider, on every page with
the converter. JPG, WebP, AVIF and video come out at quality 85, the
API's default and the slider's own starting point, so whoever left it alone
gets the same file as before. In 31 of the 107 format pairs that showed it
(every picture to PNG; JPG, PNG and WebP to BMP, TIFF, ICO and PDF) the slider
changed nothing at all.

- After converting one file to JPG, WebP, AVIF, MP4, MOV, AVI, MKV or WebM,
  the result points to Compress, which makes the file smaller by quality or,
  for JPG, WebP and AVIF, to a target size.
- A conversion whose result is over the output limit now suggests a more
  efficient target format, no longer a lower quality, which converting has no
  control for. Compress keeps its text.
- The API is unchanged: `/api/v1/convert` still takes `quality` (1–100,
  default 85).
