### Added — Video to GIF: short clips become animated GIFs

Every video FileMorph reads (MP4, MOV, AVI, MKV, WebM, FLV, WMV) now converts
to GIF, in the web UI and through `POST /api/v1/convert` with
`target_format=gif`.

- **Made for short clips:** up to 30 seconds, 10 frames per second, endless
  loop, no sound. Frames fit into 480 × 480 pixels and are never upscaled; a
  portrait clip stays portrait.
- **Good colours, small files:** two ffmpeg passes — one 256-colour palette
  for the whole clip, then every frame mapped onto it with ordered dithering,
  so areas that don't change stay identical from frame to frame.
- **No metadata:** the GIF carries nothing from the video — no location,
  device or recording date.
- **Refused, not cut short:** a video longer than 30 seconds is answered
  `400` with `X-FileMorph-Error-Code: video_too_long`, and the message names
  the way out (shorten it first, or convert to MP4 or WebM). A video above
  4096 × 2160 pixels, or one that would take longer than 85 seconds, gets
  `video_too_complex`; a file without a video picture gets `invalid_input`.
  A GIF over the output cap names a shorter clip as the fix.
- **Web UI:** with a video selected and GIF as the target, a note shows the
  limits before the upload, and the quality slider hides — it has no effect
  on GIF (image → GIF included). German and English texts.

Docs: `docs/formats.md` (Video → GIF), `docs/api-reference.md` (error codes),
README format table.
