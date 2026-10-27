### Changed — video and audio outputs no longer copy the source's metadata

Video conversions and compressions no longer copy the source file's
metadata — its tags and chapters — into the output, matching the default-on
metadata strip for images. Portrait clips stay upright, since their
rotation is applied to the frames.

Audio conversions keep only the music tags — title, artist and album
artist, album, track number, genre, and the year of the date — and no other
tags or chapters; embedded cover art was dropped before. The music tags now
carry over from Ogg and Opus files too, which keep them on the audio stream.
An output still carries the technical tags its muxer writes (encoder,
handler, language).
