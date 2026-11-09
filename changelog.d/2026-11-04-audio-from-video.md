### Added — the sound of a video as MP3: Video → audio, with a page at `/convert/video-to-mp3`

Every video format FileMorph reads — MP4, MOV, AVI, MKV, WebM, FLV and WMV —
now converts to MP3, M4A, WAV, FLAC, OGG, AAC, Opus and WMA: the result is
the video's sound. The new page "Video to MP3" ("Video in MP3") is pre-set to MP3 and
listed on `/tools`, in the footer and among the homepage's quick actions,
which now group "Video to GIF" and "Video to MP3" under "Video".

- Only the first audio track is kept. The picture, further tracks, subtitles,
  chapters and cover art are left out, and so is every tag of the video —
  location, device, recording time, and also a title or artist. A picture or
  subtitles in a codec FileMorph doesn't read don't stop the sound.
- Codecs and the `quality` mapping are those of audio → audio; 5.1 surround
  sound is mixed down to stereo for MP3, Opus and WMA, and kept for AAC,
  Vorbis, FLAC and WAV.
- A video without sound is answered with `400` and
  `X-FileMorph-Error-Code: no_audio_track`; the web UI says so in the page's
  language. An audio file over the output cap names what makes it smaller:
  MP3 or M4A instead of WAV or FLAC, or else a shorter video. The time limit
  and the tier limits apply as for every audio and video conversion.
