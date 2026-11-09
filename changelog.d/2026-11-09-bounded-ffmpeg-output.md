### Changed — ffmpeg and ffprobe error output is read back within a fixed memory bound

The converter now reads at most a fixed amount of the error output that ffmpeg
and ffprobe write: it keeps the start and the end — which carry the message it
needs to tell the user what went wrong — and drops the middle, so a file that
makes the tools log a great deal cannot grow the server's memory use. The two
streams are drained in their own threads, so the child process never stalls on
a full pipe, and the time limit, the process limits and the error messages
clients see are unchanged.
