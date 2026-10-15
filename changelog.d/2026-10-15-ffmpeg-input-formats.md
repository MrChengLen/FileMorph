### Security — FFmpeg reads uploads only in the formats FileMorph supports

The audio and video conversions and the video compressor now open uploads
with ffmpeg limited to the demuxers of the formats FileMorph accepts: MP3,
WAV, FLAC, Ogg (incl. Opus), AAC, ASF (WMA, WMV), MP4/MOV/M4A, AVI, Matroska
(MKV, WebM) and FLV, and only as a local file. ffmpeg still recognises other
formats, but refuses to open an upload in one of them; such an upload gets
`400` with `X-FileMorph-Error-Code: invalid_input` and "Could not read this
file: it is not in one of the audio or video formats FileMorph supports.
Save it as MP4 (video) or MP3 (audio) and try again." The list covers audio
and video together, so a file whose container differs from its extension
still converts as long as the container is one of these. The list is one
constant, `INPUT_DEMUXERS` in `app/converters/_ffmpeg.py`, and every ffmpeg
call on an upload goes through `media_input()` there.

Tests build each accepted input format with ffmpeg and convert it, check
that a file in another format is refused, and check the source code for any
other way into ffmpeg.
