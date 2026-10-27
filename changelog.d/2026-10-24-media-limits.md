### Changed — Audio and video conversions run with resource limits

The audio and video work of a request (conversion, video compression,
video → GIF) has one time limit, `MEDIA_SUBPROCESS_TIMEOUT_SECONDS`, now 85
seconds by default (it was 600 seconds for each ffmpeg run). The files of a
batch share it. A file that runs out of time gets a `400` (`invalid_input`)
whose message names the next step, where it used to get a `500`; in a batch,
a file whose turn comes after the time is up is not converted and says so.

- Videos larger than 4K (4096 × 2160 pixels per frame) get a `400` that asks
  for an export at 4K or lower.
- ffmpeg decodes uploads only with the decoders for the common audio, video
  and subtitle codecs of the accepted formats; a conversion that needs a
  stream in another codec gets the `400` for an unsupported format. The
  probe before video → GIF uses the same list.
- On Linux ffmpeg and ffprobe start with their address space capped at
  3 GiB, the size of each file they write capped at the request's output
  cap, a CPU-time cap, no core dump and no new privileges, and they end with
  the app process. A video compression that reaches the output cap now
  stops there and gets the `413` (`output_cap_exceeded`). ffmpeg's decoders,
  encoders and filters use 2 threads each, and both programs get the
  environment without application secrets.
- Raise `MEDIA_SUBPROCESS_TIMEOUT_SECONDS` if you convert long or HD footage
  and no CDN or proxy in front of FileMorph stops waiting sooner.
