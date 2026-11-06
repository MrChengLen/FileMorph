### Changed — a hidden quality slider no longer sends its value

In the web UI no quality slider shows for an audio target, as before for
audio → audio. A hidden slider now sends nothing, so the server's default
quality applies — before, a value set for an earlier file still decided an
MP3's or M4A's bit rate without being visible.
