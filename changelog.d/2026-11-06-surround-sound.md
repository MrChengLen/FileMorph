### Fixed — surround (5.1) sound no longer fails Video → WebM/WMV and Audio → Opus/WMA

A video or audio file with 5.1 surround sound used to fail with a generic
error on four conversions — Video → WebM, Video → WMV, Audio → Opus and
Audio → WMA — because the Opus and Windows-Media encoders reject the
surround layout that film audio (AC-3, E-AC-3, DTS) carries. The surround
sound is now mixed down to stereo for those encoders, the same way MP3
already handled it; mono and stereo sources are untouched, and AAC, Vorbis,
FLAC and WAV keep all six channels.

With the encoders no longer failing, Video → audio now also offers Opus and
WMA, so every video format converts to the full set of audio formats
(MP3, M4A, WAV, FLAC, OGG, AAC, Opus, WMA) — matching audio → audio.
