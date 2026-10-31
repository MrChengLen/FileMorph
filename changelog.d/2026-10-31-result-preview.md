### Added — the result card shows how the size changed, and a picture of an image

After converting or compressing one file, the card with the download button
says how the result's size compares to the original's — "55% smaller than the
original", above "Before 123.8 KB, now 55.9 KB" — and says just as plainly
when a result is larger ("5 times the size of the original"). The numbers are
the browser's own (the selected file and the response), not an estimate;
nothing new goes to the server.

- An image result (JPG, PNG, WebP, GIF, AVIF, BMP, ICO) shows as a small
  picture beside it, on a grey ground that keeps black and white transparent
  artwork visible. A GIF made from a video gets none (it would play endlessly
  on the card), nor does a result over 10 MB or 16 megapixels (decoding could
  exhaust a phone's memory), or one not ready within 1.5 s (the card doesn't
  wait).
- Target-size compression shows only the change, since its download label
  already names the size. A batch shows neither: its ZIP is compressed, so its
  size is not the files'.
- Screen readers hear the change and the sizes together with the download
  label.
- The pages with the converter (home, `/compress`, `/convert/…`) send the CSP
  profile `hybrid`, which allows `blob:` images; every other page keeps
  `default`.
- A result that arrives after the user picked another file or switched mode
  is dropped. Before, it still appeared, next to the newly picked file.
- Each new run frees the previous result in the browser (in the redaction
  tool, the next result does). Before, every result stayed in memory until the
  page was closed.
