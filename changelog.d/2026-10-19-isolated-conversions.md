### Changed — Table conversions and PDF compression run in their own process with memory and time limits

XLSX → CSV, CSV → XLSX, CSV → JSON, JSON → CSV and PDF compression
(`/api/v1/pdf/compress`) run in a child process, as PDF → TXT already does:
without the server's secrets in its environment, stopped after 90 seconds,
and on Linux limited to 1 GiB of address space (PDF compression: 3 GiB). A
file over these limits gets `400` with `X-FileMorph-Error-Code: invalid_input`
and a message naming the next step: split the table into smaller files, or
split the PDF with `/api/v1/pdf/split`. The child's temporary files go to the
request's own temp folder, which is removed with the request. CSV → XLSX
writes its rows to a temporary file instead of holding every cell in memory,
and the PDF → TXT child also gets a CPU-time limit (35 seconds).
