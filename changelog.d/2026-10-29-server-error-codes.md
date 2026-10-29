### Added — error codes for a failed conversion, a blocked file type, an oversized request and a busy server

More error responses now carry `X-FileMorph-Error-Code`, so a client can
branch on them instead of on the `detail` text:

- `convert_failed` / `compress_failed` (`500`) — the conversion or
  compression itself failed on `/convert` or `/compress`; the server names
  the reason only in its log;
- `file_type_not_permitted` (`400`) — the file starts like a program or
  script, on every upload route (in a batch only that file fails, without
  the code);
- `request_too_large` (`413`) — the request is larger than the server takes
  (`MAX_UPLOAD_SIZE_MB` on file endpoints, 1 MB elsewhere); the JSON body
  adds `max_size_mb`, that limit in MB;
- `server_busy` (`503`) — the server is at its global concurrency cap.

The `detail` texts stay as they were.
