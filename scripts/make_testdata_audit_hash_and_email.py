# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic QA files for the audit-log test round of PRs #217 and #218.

Generates the read-only SQL files the manual checklist refers to (SELECT and
``COPY ... TO STDOUT`` only; run them with psql against the deployment's
database):

* ``kette-pruefen.sql``          — ``VERIFY_CHAIN_SQL`` from ``app/core/audit.py``:
  the first broken row of the hash chain, or no row
* ``formate-zaehlen.sql``        — entries per ``hash_version``
* ``kopf-sichern.sql``           — the newest entry (id + record_hash), to keep
* ``alte-eintraege-export.sql``  — the format-1 entries as CSV, to keep
* ``email-daten-pruefen.sql``    — whether new entries hold email-derived data

``kette-pruefen.sql`` is taken from the code, so it always matches the version
that runs. Same call => byte-identical output on every run. Output directory
defaults to ``docs-internal/testdata/audit-hash-and-email/`` next to this repo
checkout (the folder is gitignored — commit this script, never the data) and
can be overridden as the first CLI argument.

Run:
    python scripts/make_testdata_audit_hash_and_email.py [output_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.audit import VERIFY_CHAIN_SQL  # noqa: E402

FORMATS = """\
-- FileMorph: audit entries per hash format. READ ONLY.
-- 1 = written before migration 013, 2 = written since.
SELECT hash_version, count(*) AS entries, min(occurred_at) AS first_at, max(occurred_at) AS last_at
FROM audit_events
GROUP BY hash_version
ORDER BY hash_version;
"""

HEAD = """\
-- FileMorph: the newest audit entry. READ ONLY. Keep id and record_hash.
SELECT id, occurred_at, hash_version, record_hash
FROM audit_events
ORDER BY id DESC
LIMIT 1;
"""

EXPORT = """\
-- FileMorph: the format-1 audit entries as CSV on standard output. READ ONLY.
COPY (
    SELECT id, event_type, occurred_at, record_hash
    FROM audit_events
    WHERE hash_version = 1
    ORDER BY id
) TO STDOUT WITH CSV HEADER;
"""

EMAIL = """\
-- FileMorph: does the audit log still store email-derived data? READ ONLY.

-- 1) The newest entry that still holds an email hash or domain, in Berlin time.
--    Must lie before the deploy of #218 and no later than 2026-10-12 23:59.
SELECT max(occurred_at) AT TIME ZONE 'Europe/Berlin' AS last_with_email_data
FROM audit_events
WHERE payload_json LIKE '%"email_hash"%' OR payload_json LIKE '%"email_domain"%';

-- 2) The 10 newest entries. None may show email_hash or email_domain in
--    payload_json; names_account is true (t) where an account was named.
SELECT id, occurred_at AT TIME ZONE 'Europe/Berlin' AS at_berlin, event_type,
       hash_version, actor_user_id IS NOT NULL AS names_account, payload_json
FROM audit_events
ORDER BY id DESC
LIMIT 10;
"""


def main() -> None:
    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else ROOT / "docs-internal" / "testdata" / "audit-hash-and-email"
    )
    out.mkdir(parents=True, exist_ok=True)

    chain = (
        "-- FileMorph: first broken row of the audit hash chain, or no row. READ ONLY.\n"
        + VERIFY_CHAIN_SQL.strip()
        + ";\n"
    )
    files = {
        "kette-pruefen.sql": chain,
        "formate-zaehlen.sql": FORMATS,
        "kopf-sichern.sql": HEAD,
        "alte-eintraege-export.sql": EXPORT,
        "email-daten-pruefen.sql": EMAIL,
    }
    for name, text in files.items():
        (out / name).write_bytes(text.encode("utf-8"))

    for f in sorted(out.iterdir()):
        if f.is_file():
            print(f"{f.name}  ({f.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
