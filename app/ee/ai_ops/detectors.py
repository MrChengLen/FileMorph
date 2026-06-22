# SPDX-License-Identifier: LicenseRef-FileMorph-Commercial
"""Deterministic PII detectors (no ML, no external calls).

Every detector here is regex + a structural check (mod-97 for IBANs, Luhn for
payment cards, octet range for IPv4). That means near-zero false negatives on
these *structured* entity types — the property that matters for a compliance
feature, where a missed item is the failure mode. Free-text PII (names,
addresses) needs NER and is a separate checkpoint; it is intentionally absent
here rather than approximated badly.

A detector is a callable ``(text) -> list[PiiSpan]``. ``detect`` runs the
selected detectors, then merges overlapping spans so the redaction layer never
double-processes a character range (e.g. a number that trips both the IBAN and
card matchers). Confidence is 1.0 for checksum-validated types; phone numbers
carry 0.85 because a leading-zero digit run is inherently ambiguous and the UI
surfaces lower-confidence items for review.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

# Stable entity-type identifiers. The UI maps these to localized labels via the
# i18n catalogue (DE/EN) — never hardcode display strings here.
EMAIL = "EMAIL"
IBAN = "IBAN"
PHONE = "PHONE"
IPV4 = "IPV4"
CREDIT_CARD = "CREDIT_CARD"

ENTITY_TYPES: tuple[str, ...] = (EMAIL, IBAN, PHONE, IPV4, CREDIT_CARD)


@dataclass(frozen=True, slots=True)
class PiiSpan:
    """One detected piece of PII, located by character offset in the source.

    ``start``/``end`` are Python slice indices into the text the span was
    detected in (``text[start:end] == value``). ``confidence`` is 1.0 for
    checksum-validated types and lower for heuristic ones.
    """

    entity_type: str
    value: str
    start: int
    end: int
    confidence: float


# ──────────────────────────────────────────────────────────────────────────
# Structural validators
# ──────────────────────────────────────────────────────────────────────────


def _iban_valid(candidate: str) -> bool:
    """ISO 13616 / ISO 7064 mod-97 check on a (possibly spaced) IBAN string."""
    iban = candidate.replace(" ", "").upper()
    if not 15 <= len(iban) <= 34:
        return False
    rearranged = iban[4:] + iban[:4]
    # A→10 … Z→35, digits unchanged; base-36 gives exactly that mapping.
    try:
        numeric = "".join(str(int(c, 36)) for c in rearranged)
    except ValueError:
        return False
    return int(numeric) % 97 == 1


def _luhn_valid(digits: str) -> bool:
    """Luhn (mod-10) checksum used by payment-card numbers."""
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        d = ord(ch) - 48
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ──────────────────────────────────────────────────────────────────────────
# Detectors
# ──────────────────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# IBAN written compactly or in conventional 4-char groups (single spaces).
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4})*\s?[A-Z0-9]{1,4}\b")
# German/international phone: +49 / 0049 / national leading 0, then separated
# digits. Deliberately conservative; digit count is checked below.
_PHONE_RE = re.compile(r"(?<!\d)(?:\+49|0049|0)[\d\s/().\-]{5,16}\d(?!\d)")
_IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
# 13–19 digits with optional single space/dash separators (card-like runs).
_CARD_RE = re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])")
# A three-group date (01.02.2024 / 01/02/2024 / 2024-01-02). The phone pattern's
# separator class includes ".", "/" and "-", so a date otherwise slips through.
_DATE_LIKE_RE = re.compile(r"^\d{1,4}[./-]\d{1,2}[./-]\d{1,4}$")


def _detect_email(text: str) -> list[PiiSpan]:
    return [PiiSpan(EMAIL, m.group(), m.start(), m.end(), 1.0) for m in _EMAIL_RE.finditer(text)]


def _detect_iban(text: str) -> list[PiiSpan]:
    out: list[PiiSpan] = []
    for m in _IBAN_RE.finditer(text):
        if _iban_valid(m.group()):
            out.append(PiiSpan(IBAN, m.group(), m.start(), m.end(), 1.0))
    return out


def _detect_phone(text: str) -> list[PiiSpan]:
    out: list[PiiSpan] = []
    for m in _PHONE_RE.finditer(text):
        token = m.group()
        if _DATE_LIKE_RE.match(token.strip()):
            continue  # a date, not a phone number
        digits = re.sub(r"\D", "", token)
        if 7 <= len(digits) <= 15:
            out.append(PiiSpan(PHONE, token, m.start(), m.end(), 0.85))
    return out


def _detect_ipv4(text: str) -> list[PiiSpan]:
    out: list[PiiSpan] = []
    for m in _IPV4_RE.finditer(text):
        if all(0 <= int(octet) <= 255 for octet in m.group().split(".")):
            out.append(PiiSpan(IPV4, m.group(), m.start(), m.end(), 1.0))
    return out


def _detect_card(text: str) -> list[PiiSpan]:
    out: list[PiiSpan] = []
    for m in _CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            out.append(PiiSpan(CREDIT_CARD, m.group(), m.start(), m.end(), 1.0))
    return out


_DETECTORS: dict[str, Callable[[str], list[PiiSpan]]] = {
    EMAIL: _detect_email,
    IBAN: _detect_iban,
    PHONE: _detect_phone,
    IPV4: _detect_ipv4,
    CREDIT_CARD: _detect_card,
}


def merge_spans(spans: list[PiiSpan], text: str) -> list[PiiSpan]:
    """Collapse overlapping/adjacent spans into non-overlapping intervals.

    Two detectors can flag overlapping ranges (a digit run that is both
    IBAN-shaped and card-shaped). Redaction must operate on disjoint intervals,
    so we union them. The merged span keeps the higher-confidence entity type;
    a genuinely mixed interval is labelled with that winning type (the caller
    redacts the whole range regardless of label).
    """
    if not spans:
        return []
    ordered = sorted(spans, key=lambda s: (s.start, s.end))
    merged: list[PiiSpan] = []
    for s in ordered:
        if merged and s.start < merged[-1].end:
            prev = merged[-1]
            new_end = max(prev.end, s.end)
            winner = prev if prev.confidence >= s.confidence else s
            merged[-1] = PiiSpan(
                winner.entity_type,
                text[prev.start : new_end],
                prev.start,
                new_end,
                max(prev.confidence, s.confidence),
            )
        else:
            merged.append(s)
    return merged


def detect(text: str, entity_types: tuple[str, ...] | None = None) -> list[PiiSpan]:
    """Detect PII of the requested types, returning merged, sorted spans.

    ``entity_types=None`` runs every detector. Unknown type names are ignored
    (so a caller passing a future NER type before it exists degrades quietly
    rather than crashing). Result is ordered by position with no overlaps.
    """
    selected = ENTITY_TYPES if entity_types is None else entity_types
    found: list[PiiSpan] = []
    for name in selected:
        detector = _DETECTORS.get(name)
        if detector is not None:
            found.extend(detector(text))
    return merge_spans(found, text)
