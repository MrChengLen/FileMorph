# SPDX-License-Identifier: LicenseRef-FileMorph-Commercial
"""Unit tests for the deterministic PII redaction engine (app.ee.ai_ops).

No app/DB/route imports — the engine is standalone, so these run fast and
isolated. The load-bearing test is the fail-closed verification pass: a bug in
span application must surface as ``verification_passed is False`` / a raised
``RedactionVerificationError``, never a silently half-redacted output.
"""

import pytest

from app.ee.ai_ops import detectors as det
from app.ee.ai_ops import redaction as rd
from app.ee.ai_ops.detectors import (
    CREDIT_CARD,
    EMAIL,
    IBAN,
    IPV4,
    PHONE,
    detect,
)

# Canonical valid German example IBAN (mod-97 == 1), both spaced and compact.
VALID_IBAN_SPACED = "DE89 3704 0044 0532 0130 00"
VALID_IBAN_COMPACT = "DE89370400440532013000"
# Visa test number (Luhn-valid).
VALID_CARD = "4111 1111 1111 1111"


# ---------------------------------------------------------------------------
# detectors — positive
# ---------------------------------------------------------------------------


def test_detect_email():
    spans = detect("Bitte an max.mustermann@beispiel.de schreiben.")
    assert [s.entity_type for s in spans] == [EMAIL]
    assert spans[0].value == "max.mustermann@beispiel.de"


def test_detect_iban_spaced_and_compact():
    spaced = detect(f"IBAN: {VALID_IBAN_SPACED}")
    assert [s.entity_type for s in spaced] == [IBAN]
    assert spaced[0].value == VALID_IBAN_SPACED

    compact = detect(f"Konto {VALID_IBAN_COMPACT} bei der Bank")
    assert [s.entity_type for s in compact] == [IBAN]
    assert compact[0].value == VALID_IBAN_COMPACT


def test_detect_iban_does_not_swallow_following_word():
    spans = detect(f"{VALID_IBAN_SPACED} Betrag 100 Euro")
    assert spans[0].value == VALID_IBAN_SPACED  # stops at the IBAN, not "Betrag"


def test_detect_phone_variants():
    for sample in ("+49 30 1234567", "0049 89 123456", "0301234567"):
        spans = detect(sample, (PHONE,))
        assert len(spans) == 1, sample
        assert spans[0].entity_type == PHONE
        assert spans[0].confidence == pytest.approx(0.85)


def test_detect_ipv4():
    spans = detect("Server 192.168.0.1 erreichbar")
    assert [s.entity_type for s in spans] == [IPV4]
    assert spans[0].value == "192.168.0.1"


def test_detect_credit_card_luhn_valid():
    spans = detect(f"Karte {VALID_CARD} gültig")
    assert [s.entity_type for s in spans] == [CREDIT_CARD]


def test_detect_multiple_entities_sorted():
    text = "Mail a@b.de, Konto " + VALID_IBAN_COMPACT
    spans = detect(text)
    assert [s.entity_type for s in spans] == [EMAIL, IBAN]
    assert spans[0].start < spans[1].start


# ---------------------------------------------------------------------------
# detectors — negative (checksums / bounds reject invalid values)
# ---------------------------------------------------------------------------


def test_invalid_iban_checksum_rejected():
    assert detect("DE00 0000 0000 0000 0000 00", (IBAN,)) == []


def test_invalid_card_luhn_rejected():
    assert detect("4111 1111 1111 1112", (CREDIT_CARD,)) == []


def test_invalid_ipv4_octet_rejected():
    assert detect("999.1.1.1", (IPV4,)) == []


def test_short_number_not_phone():
    assert detect("Nr 0123", (PHONE,)) == []


@pytest.mark.parametrize("date", ["01.02.2024", "1.2.2024", "01/02/2024", "2024-01-02"])
def test_date_not_matched_as_phone(date):
    # The phone separator class includes ".", "/" and "-", so a three-group date
    # would otherwise be flagged as a phone number.
    assert detect(f"Termin am {date} um 10 Uhr", (PHONE,)) == []


def test_phone_still_detected_alongside_dates():
    spans = detect("Am 01.02.2024 unter 030 1234567 erreichbar", (PHONE,))
    assert len(spans) == 1
    assert "030 1234567" in spans[0].value


def test_plain_text_has_no_pii():
    assert detect("Dies ist ein ganz normaler Satz ohne Daten.") == []


# ---------------------------------------------------------------------------
# redaction modes
# ---------------------------------------------------------------------------


def test_redact_replace_default():
    result = rd.redact_text("Mail: a@b.de")
    assert result.text == "Mail: [EMAIL]"
    assert result.entities_redacted == 1
    assert result.verification_passed is True


def test_redact_mask_preserves_length():
    result = rd.redact_text("Mail: a@b.de", (EMAIL,), mode=rd.MASK)
    assert result.text == "Mail: " + "*" * len("a@b.de")
    assert result.verification_passed is True


def test_redact_remove_deletes_value():
    result = rd.redact_text(f"Konto {VALID_IBAN_COMPACT} Ende", (IBAN,), mode=rd.REMOVE)
    assert result.text == "Konto  Ende"  # value removed, surrounding spaces remain
    assert result.verification_passed is True


def test_redact_unknown_mode_raises():
    with pytest.raises(ValueError):
        rd.redact_text("a@b.de", mode="blackout")


# ---------------------------------------------------------------------------
# scope — only requested types are redacted
# ---------------------------------------------------------------------------


def test_scope_limits_redaction():
    text = f"Mail a@b.de Konto {VALID_IBAN_COMPACT}"
    result = rd.redact_text(text, (EMAIL,))
    assert "[EMAIL]" in result.text
    assert VALID_IBAN_COMPACT in result.text  # IBAN out of scope, untouched
    assert result.verification_passed is True  # residual scoped to EMAIL only


# ---------------------------------------------------------------------------
# fail-closed verification (the load-bearing guarantee)
# ---------------------------------------------------------------------------


def test_verification_passes_on_clean_output():
    result = rd.redact_text(f"a@b.de {VALID_IBAN_COMPACT} 192.168.0.1")
    assert result.verification_passed is True
    assert result.residual == []


def test_verification_catches_incomplete_redaction(monkeypatch):
    # Simulate an application bug: _apply leaves the text untouched. The
    # verification re-scan must then flag the residual PII and fail closed.
    monkeypatch.setattr(rd, "_apply", lambda text, spans, mode: text)
    result = rd.redact_text("Mail: a@b.de")
    assert result.verification_passed is False
    assert [s.entity_type for s in result.residual] == [EMAIL]


def test_redact_or_raise_fails_closed(monkeypatch):
    monkeypatch.setattr(rd, "_apply", lambda text, spans, mode: text)
    with pytest.raises(rd.RedactionVerificationError):
        rd.redact_text_or_raise("Mail: a@b.de")


# ---------------------------------------------------------------------------
# overlap merge
# ---------------------------------------------------------------------------


def test_merge_collapses_overlapping_spans():
    text = "value"
    spans = [
        det.PiiSpan(IBAN, "valu", 0, 4, 1.0),
        det.PiiSpan(CREDIT_CARD, "alue", 1, 5, 1.0),
    ]
    merged = det.merge_spans(spans, text)
    assert len(merged) == 1
    assert (merged[0].start, merged[0].end) == (0, 5)


# ---------------------------------------------------------------------------
# detector hardening (2026-06-22 audit): recall fixes + FP guards
# ---------------------------------------------------------------------------


def test_detect_ipv4_at_sentence_end():
    # Recall fix: an IP immediately before a sentence period used to be missed.
    spans = detect("Zugriff aus 192.168.0.1.")
    assert [s.entity_type for s in spans] == [IPV4]
    assert spans[0].value == "192.168.0.1"


@pytest.mark.parametrize("text", ["1.2.3.4.5", "192.168.0.1.2"])
def test_ipv4_five_octet_still_rejected(text):
    # The sentence-end fix must NOT weaken the longer-octet-run guard.
    assert detect(text, (IPV4,)) == []


def test_detect_iban_lowercase_wins_over_phone():
    # Recall fix: a lowercase IBAN is now detected (was missed → only a stray
    # PHONE false-match). Pins that merge_spans keeps IBAN over the phone span.
    spans = detect("konto de89 3704 0044 0532 0130 00 ende")
    assert [s.entity_type for s in spans] == [IBAN]


@pytest.mark.parametrize(
    "text",
    ["DE89-3704-0044-0532-0130-00", "DE89.3704.0044.0532.0130.00"],
)
def test_detect_iban_hyphen_and_dot_grouped(text):
    assert [s.entity_type for s in detect(text, (IBAN,))] == [IBAN]


@pytest.mark.parametrize(
    "text",
    [
        "Version 1.2.3.4",
        "01.02.2024",
        "1.234,56 EUR",
        "030-1234-5678",
        "978-3-16-148410-0",
        "AB12-3456-7890-1234",
    ],
)
def test_iban_separators_no_false_positive(text):
    # The looser separator regex must not over-match: mod-97 stays the hard filter.
    assert detect(text, (IBAN,)) == []


def test_all_identical_digit_card_rejected():
    assert detect("0000000000000000", (CREDIT_CARD,)) == []
    assert [s.entity_type for s in detect(VALID_CARD, (CREDIT_CARD,))] == [CREDIT_CARD]


def test_all_zero_invalid_iban_not_card():
    # Bad-checksum all-zero IBAN no longer slips through as a Luhn-valid card.
    assert CREDIT_CARD not in [s.entity_type for s in detect("DE00 0000 0000 0000 0000 00")]
