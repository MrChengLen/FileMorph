# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic QA fixtures for the "audit log stores no IP addresses" test round.

Generates the files the manual checklist refers to:

* ``testbild.png``       — small PNG, converted to JPG without signing in
* ``foto.jpg``           — small JPEG, compressed while signed in
* ``audit-pruefung.sql`` — read-only queries (SELECT only) that show whether
  new audit entries still carry an IP address

Same call => byte-identical output on every run. Output directory defaults to
``docs-internal/testdata/audit-no-ip/`` next to this repo checkout (the folder
is gitignored — commit this script, never the data) and can be overridden as
the first CLI argument.

Run:
    python scripts/make_testdata_audit_no_ip.py [output_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

AUDIT_QUERIES = """\
-- FileMorph: does the audit log still store IP addresses? READ ONLY (SELECT only).

-- 1) The 15 newest audit entries. has_ip must be false (f) for every entry written
--    after the deploy; older entries may still show true (t) until the column is
--    dropped by its own migration.
SELECT id, occurred_at, event_type, actor_ip IS NOT NULL AS has_ip
FROM audit_events
ORDER BY id DESC
LIMIT 15;

-- 2) Entries WITH an IP address written in the last hour (run it right after the
--    test steps) - must be 0.
SELECT count(*) AS entries_with_ip_last_hour
FROM audit_events
WHERE actor_ip IS NOT NULL
  AND occurred_at > now() - interval '1 hour';
"""


def main() -> None:
    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else (Path(__file__).resolve().parent.parent / "docs-internal" / "testdata" / "audit-no-ip")
    )
    out.mkdir(parents=True, exist_ok=True)

    Image.new("RGB", (120, 80), color=(30, 140, 90)).save(out / "testbild.png", "PNG")
    Image.new("RGB", (320, 240), color=(200, 110, 40)).save(out / "foto.jpg", "JPEG", quality=95)
    (out / "audit-pruefung.sql").write_bytes(AUDIT_QUERIES.encode("utf-8"))

    for f in sorted(out.iterdir()):
        if f.is_file():
            print(f"{f.name:20} {f.stat().st_size:8} bytes")


if __name__ == "__main__":
    main()
