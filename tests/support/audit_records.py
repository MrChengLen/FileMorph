# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deletion records the audit chain checks must judge alike.

test_audit_log.py runs them through ``verify_chain`` on SQLite,
test_audit_postgres.py through ``verify_chain`` and ``VERIFY_CHAIN_SQL`` on
Postgres. Each case is a record of the deletion just before an expired start:
only the app's own payload, written by now, vouches for that start; every
other payload names nothing, and the SQL check must still answer.
"""

from __future__ import annotations

import pytest

from app.core.audit import RETENTION_LINK_KEY, _canonical_payload

# Spelled out, because tools and editors may decode an escape in the source.
_BACKSLASH = chr(92)

# id, payload ("LINK" stands for the hash the record names; None for the
# payload the app writes), days after now the record is dated, vouches
_CASES = [
    ("well-formed", None, 0, True),
    ("future-dated", None, 1500, False),
    ("not-json", "not json", 0, False),
    ("not-an-object", "[1]", 0, False),
    ("not-a-string", '{"' + RETENTION_LINK_KEY + '":7}', 0, False),
    ("escape", '{"' + RETENTION_LINK_KEY + '":"LINK","x":"' + _BACKSLASH + 'u0041"}', 0, False),
    ("nan", '{"' + RETENTION_LINK_KEY + '":"LINK","x":NaN}', 0, False),
    ("too-long", '{"' + RETENTION_LINK_KEY + '":"LINK","x":"' + "y" * 150 + '"}', 0, False),
]

RECORD_CASES = [
    pytest.param(payload, days, vouches, id=case_id) for case_id, payload, days, vouches in _CASES
]


def record_payload(template: str | None, link: str) -> str:
    """The payload of a case, naming ``link``."""
    if template is None:
        return _canonical_payload({"deleted": 1, RETENTION_LINK_KEY: link})
    return template.replace("LINK", link)
