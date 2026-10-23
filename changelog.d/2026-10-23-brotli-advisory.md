### Security — brotli 1.2.1: out-of-bounds write in the decoder fixed

brotli, which WeasyPrint pulls in through fonttools, moves from 1.2.0 to
1.2.1. That fixes CVE-2026-111497 (PYSEC-2026-4322, critical), published on
2026-10-22: a crafted Brotli stream could make the decoder write past its
buffer. Every deployment should update. The new version is a floor in
`requirements.txt`, so a later re-lock cannot fall back below it; nothing
else in the lockfile moved.
