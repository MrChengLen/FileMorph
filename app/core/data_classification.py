# SPDX-License-Identifier: AGPL-3.0-or-later
"""NEU-C.3: BSI-style data-classification taxonomy + per-request resolution.

Behörden, Krankenhäuser and Anwaltskanzleien need a consistent
vocabulary for data sensitivity that propagates through the audit
log so a downstream auditor can answer "what classification of data
was processed in this request" from a SQL dump alone. This module
pins the vocabulary, validates an incoming ``X-Data-Classification``
request header against it, and echoes the resolved value back so
the request → audit-log → verifier round-trip is observable
end-to-end.

Vocabulary (lower-case, English — chosen so ISO 27001 / BSI
Schutzbedarf taxonomies can both read it without translation):

* ``public`` — open data: published reports, integration tests,
  public-API documentation samples.
* ``internal`` — restricted to the operating organisation.
  **Default when the header is absent**: a service that doesn't
  know what its caller is sending should err on the safer side
  rather than silently treat unflagged input as public.
* ``confidential`` — limited audience inside the org: HR, regular
  patient data, mandate file content for a specific case team.
* ``restricted`` — strictest tier: patient data subject to MDR
  pseudonymisation, government VS-Geheim+, KRITIS-relevant
  operational data, bank/legal secrets.

Mapping onto adjacent taxonomies (informational — both sides of
this map evolve, so we pin our vocabulary in code and document the
correspondence in prose):

* ``internal`` ≈ BSI Schutzbedarf *normal* / VS-NfD
* ``confidential`` ≈ BSI Schutzbedarf *hoch* / VS-Vertraulich
* ``restricted`` ≈ BSI Schutzbedarf *sehr hoch* / VS-Geheim and above

Failure mode
------------
An invalid value (anything not in the vocabulary, after trim and
lowercase) is logged at WARNING and falls back to ``internal``. We
do not 400 the request — a typo in a Compliance customer's pipeline
should not break their production flow at the network boundary, and
the audit-log entry records the raw input on the warning line for
forensics. If a deployment wants strict rejection, that's a thin
wrapper around :func:`normalize_classification` in a custom
middleware, not a default in this module.
"""

from __future__ import annotations

import logging
from typing import FrozenSet

logger = logging.getLogger(__name__)


VALID_CLASSIFICATIONS: FrozenSet[str] = frozenset(
    {
        "public",
        "internal",
        "confidential",
        "restricted",
    }
)

DEFAULT_CLASSIFICATION: str = "internal"

REQUEST_HEADER: str = "X-Data-Classification"
RESPONSE_HEADER: str = "X-Data-Classification"


def normalize_classification(raw: str | None) -> tuple[str, bool]:
    """Validate an incoming ``X-Data-Classification`` header value.

    Returns ``(classification, was_valid)``:

    * ``raw`` is ``None`` or empty → ``(DEFAULT, True)``. Absence of a
      header is the silent path; the caller didn't claim a value, so
      we don't warn.
    * ``raw`` matches the vocabulary after ``.strip().lower()`` →
      ``(canonical_lower, True)``.
    * Otherwise → ``(DEFAULT, False)``. The middleware logs the raw
      input on the warning line so an upstream typo surfaces in
      structured logs without breaking the request.
    """
    if not raw:
        return DEFAULT_CLASSIFICATION, True
    candidate = raw.strip().lower()
    if candidate in VALID_CLASSIFICATIONS:
        return candidate, True
    return DEFAULT_CLASSIFICATION, False
