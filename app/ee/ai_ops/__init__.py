# SPDX-License-Identifier: LicenseRef-FileMorph-Commercial
"""AI file operations (Enterprise Edition — commercial-only, see app/ee/README.md).

A paid-only add-on for filemorph.io customers: AI-assisted operations (PII
redaction first; generative document operations later). It is deliberately
*separate* from ``app.converters`` because AI operations have a different shape
— not ``(src_fmt, tgt_fmt)`` pairs, and they carry a per-operation cost/consent
profile. The flagship — PII redaction — runs **locally on CPU with no external
call**, which is both cheap and the strongest GDPR story (the file never leaves
the server).

This module ships the deterministic redaction engine: no HTTP route, no DB, no
third-party dependency. Structured PII (IBAN, email, phone, IPv4, payment-card
numbers) is matched by regex + checksum, so recall on these types is
effectively complete. Name/address detection (NER) and the optional LLM quality
booster are later checkpoints.

Design commitment: **fail-closed**. ``redact_text`` always runs a verification
pass over its own output and reports any residual match. A half-redacted
document is the single worst output this feature can produce, so the caller
MUST treat ``verification_passed is False`` as an error, never ship the result.

Margin-opacity rule: any cost-revealing value (model IDs, token math, cost→
credit mapping) lives in private environment, never in this source — the
client- and repo-facing surfaces are credit-denominated only.
"""

from __future__ import annotations

from app.ee.ai_ops.detectors import ENTITY_TYPES, PiiSpan, detect
from app.ee.ai_ops.redaction import (
    RedactionResult,
    RedactionVerificationError,
    redact_text,
)

__all__ = [
    "ENTITY_TYPES",
    "PiiSpan",
    "detect",
    "RedactionResult",
    "RedactionVerificationError",
    "redact_text",
]
