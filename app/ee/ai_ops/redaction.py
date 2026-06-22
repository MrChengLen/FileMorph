# SPDX-License-Identifier: LicenseRef-FileMorph-Commercial
"""Text redaction with a mandatory fail-closed verification pass.

This operates on plain strings — the format handlers (DOCX/XLSX/PDF) are a
later checkpoint and will reuse this core. The non-negotiable property is the
verification pass: after applying redactions, we re-run detection over the
*output* and report any residual match. A half-redacted document is the worst
possible result for a compliance feature, so ``redact_text`` never trusts that
its own application step was complete — it checks. The caller treats
``verification_passed is False`` as a hard error (HTTP 500), never a download.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ee.ai_ops.detectors import PiiSpan, detect

# Redaction styles. ``replace`` is the default: it preserves document
# readability ("contact [EMAIL] for details") while removing the value.
REPLACE = "replace"  # value → [ENTITY_TYPE]
MASK = "mask"  # value → asterisks of equal length
REMOVE = "remove"  # value → "" (deleted)

REDACTION_MODES: tuple[str, ...] = (REPLACE, MASK, REMOVE)


class RedactionVerificationError(Exception):
    """Raised when redacted output still contains detectable PII.

    The route layer maps this to a generic 500 (never leaking the residual
    values to the client). It means a bug in span application, not user error —
    fail closed: do not return the document.
    """

    def __init__(self, residual: list[PiiSpan]):
        super().__init__(f"Redaction verification failed: {len(residual)} item(s) remain.")
        self.residual = residual


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """Outcome of a redaction pass over one text.

    ``spans`` are the merged ranges that were redacted. ``residual`` is what a
    re-scan of ``text`` found — empty iff ``verification_passed``. Callers must
    check ``verification_passed`` before using ``text``.
    """

    text: str
    spans: list[PiiSpan]
    entities_redacted: int
    verification_passed: bool
    residual: list[PiiSpan]


def replacement_for(entity_type: str, value: str, mode: str) -> str:
    """The redacted replacement string for one value under ``mode``.

    Shared by the text engine and the package-level (ZIP/XML) redaction path in
    ``formats.py`` so both produce identical placeholders. ``REPLACE`` →
    ``[TYPE]``, ``MASK`` → equal-length asterisks, ``REMOVE`` → empty string.
    """
    if mode == REMOVE:
        return ""
    if mode == MASK:
        return "*" * len(value)
    return f"[{entity_type}]"


def _replacement(span: PiiSpan, mode: str) -> str:
    return replacement_for(span.entity_type, span.value, mode)


def _apply(text: str, spans: list[PiiSpan], mode: str) -> str:
    """Replace each (disjoint) span. Walk back-to-front so earlier offsets
    stay valid as later ones are rewritten."""
    out = text
    for span in sorted(spans, key=lambda s: s.start, reverse=True):
        out = out[: span.start] + _replacement(span, mode) + out[span.end :]
    return out


def redact_text(
    text: str,
    entity_types: tuple[str, ...] | None = None,
    mode: str = REPLACE,
) -> RedactionResult:
    """Detect and redact PII in ``text``, then verify the output is clean.

    ``entity_types=None`` redacts every supported type. ``mode`` is one of
    ``REDACTION_MODES``. The returned result always reflects a verification
    re-scan; on residual leakage ``verification_passed`` is False and the
    caller must not ship ``text``. Use ``redact_text_or_raise`` for the
    fail-closed variant.
    """
    if mode not in REDACTION_MODES:
        raise ValueError(f"Unknown redaction mode: {mode!r}")

    spans = detect(text, entity_types)
    redacted = _apply(text, spans, mode)

    # Verification pass: re-detect on the output with the same scope.
    residual = detect(redacted, entity_types)
    return RedactionResult(
        text=redacted,
        spans=spans,
        entities_redacted=len(spans),
        verification_passed=not residual,
        residual=residual,
    )


def redact_text_or_raise(
    text: str,
    entity_types: tuple[str, ...] | None = None,
    mode: str = REPLACE,
) -> RedactionResult:
    """Fail-closed wrapper: ``redact_text`` but raise on residual leakage."""
    result = redact_text(text, entity_types, mode)
    if not result.verification_passed:
        raise RedactionVerificationError(result.residual)
    return result


__all__ = [
    "REPLACE",
    "MASK",
    "REMOVE",
    "REDACTION_MODES",
    "RedactionResult",
    "RedactionVerificationError",
    "redact_text",
    "redact_text_or_raise",
    "replacement_for",
]
