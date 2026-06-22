# SPDX-License-Identifier: AGPL-3.0-or-later
"""Landing-page content for the PII-redaction tool (/redact).

Like ``convert_pairs.PAIR_CONTENT``, the prose lives as plain bilingual data
(``de`` / ``en``), not gettext, so the ``.po`` catalogue stays lean — only the
page *chrome* (section headings) and the JS runtime strings are translated via
``_()``. The page pairs a genuinely useful, free tool (the findings preview /
``detect``) with unique, honest content, which is what keeps it penalty-safe.

Honesty is load-bearing here: the feature detects only the five *structured*
types and does NOT detect names/addresses (no NER) or support PDF. Every block
that could be read as a compliance promise states that limit plainly — the
``not_covered`` and ``legal_notice`` fields are not optional decoration.
"""

from __future__ import annotations

from app.core.i18n import normalize_locale

# Per-locale fields:
#   title         — SEO <title> sans the " | FileMorph" suffix
#   meta          — meta description (<=160 chars)
#   h1 / hero     — visible heading + one-line sub-heading
#   what_detects  — list of (label, detail) for the five structured types
#   formats       — one line on supported inputs
#   not_covered   — honest limits (PDF, names/addresses, no guarantee)
#   how_it_works  — list of (step_label, step_text) for the two-phase flow
#   when          — "when to use" paragraph
#   trust         — EU / stateless / open-source / no third-party AI block
#   legal_notice  — persistent inline disclaimer shown next to the result
#   faq           — list of (question, answer), 3 entries
REDACT_CONTENT: dict[str, dict] = {
    "en": {
        "title": "Redact PII in documents — free preview",
        "meta": (
            "Detect and redact IBANs, emails, phone numbers and more in TXT, DOCX and XLSX. "
            "Free findings preview — no account. EU-hosted, files deleted right after."
        ),
        "h1": "Redact PII in documents",
        "hero": (
            "Find and remove IBANs, emails, phone numbers, IP addresses and credit-card "
            "numbers from TXT, DOCX and XLSX — free findings preview, paid file output."
        ),
        "what_detects": [
            ("IBAN", "Regex + ISO 13616 mod-97 checksum"),
            ("Email address", "Local-part + domain pattern"),
            ("Phone number", "Digit runs — flagged for review (confidence 0.85)"),
            ("IPv4 address", "Dotted quad with octet-range validation"),
            ("Credit-card number", "13–19 digits passing the Luhn checksum"),
        ],
        "formats": "TXT, DOCX (Word) and XLSX (Excel).",
        "not_covered": (
            "PDF is not supported yet, and free-text names and postal addresses are not "
            "detected — that needs named-entity recognition, which is on the roadmap. This "
            "tool assists your review; it does not guarantee complete anonymization, and you "
            "remain responsible for checking the result before sharing it."
        ),
        "how_it_works": [
            (
                "Upload & scan (free)",
                "Upload a TXT, DOCX or XLSX file and get a findings list with a count per "
                "type. Nothing is charged and no file is produced yet.",
            ),
            (
                "Review the findings",
                "See what was found before committing. Phone numbers carry a lower confidence "
                "score and are flagged so you can decide whether to include them.",
            ),
            (
                "Redact & download (paid)",
                "Confirm to produce the cleaned file — each value is replaced with a label, "
                "masked, or removed. The output is re-scanned before release; if anything "
                "remains, no file is returned (fail-closed).",
            ),
        ],
        "when": (
            "Use it before sharing or archiving a document that contains financial data, "
            "contact details or technical identifiers you must not leak — support tickets "
            "with IBANs, test-data exports with emails, XLSX reports that hold internal IP "
            "ranges or card numbers."
        ),
        "trust": (
            "Processed on EU servers with no third-party AI — detection is deterministic "
            "(regex + checksums), not a language model. Your file is held in memory and "
            "deleted right after processing; detected values are never logged or stored. The "
            "redaction engine is open source (AGPLv3) and auditable."
        ),
        "legal_notice": (
            "Assists with PII removal — review before sharing. Detects emails, IBANs, phone "
            "numbers, IPs and card numbers. Does not detect names or addresses. Not a "
            "guarantee of complete anonymization."
        ),
        "faq": [
            (
                "Why can't it redact names and addresses?",
                "Detecting structured values like IBANs or card numbers is a checksum problem "
                "with near-zero misses. Detecting names needs a language model (NER), which "
                "adds false positives and external processing. This tool solves the "
                "structured problem reliably; name/address detection is a separate, planned "
                "scope — so review the result for those yourself.",
            ),
            (
                "What does 'fail-closed' mean?",
                "After redacting, the engine re-scans the output. If any value it redacted is "
                "still detectable, the file is not released — you get an error instead of a "
                "half-redacted document. We block rather than hand back a broken result.",
            ),
            (
                "Is the scan really free?",
                "Yes. Uploading a file and seeing the findings (counts and types) costs "
                "nothing and needs no account. Downloading the redacted file is the paid "
                "step — it uses your plan's monthly redaction credits.",
            ),
        ],
    },
    "de": {
        "title": "PII in Dokumenten schwärzen — Vorschau",
        "meta": (
            "IBANs, E-Mails, Telefonnummern und mehr in TXT, DOCX und XLSX erkennen und "
            "schwärzen. Kostenlose Vorschau — kein Konto, EU-gehostet, sofort gelöscht."
        ),
        "h1": "PII in Dokumenten schwärzen",
        "hero": (
            "IBANs, E-Mail-Adressen, Telefonnummern, IP-Adressen und Kreditkartennummern aus "
            "TXT, DOCX und XLSX entfernen — kostenlose Fundstellen-Vorschau, "
            "kostenpflichtige Ausgabedatei."
        ),
        "what_detects": [
            ("IBAN", "Regex + ISO-13616-Modulo-97-Prüfziffer"),
            ("E-Mail-Adresse", "Lokalteil- + Domain-Muster"),
            ("Telefonnummer", "Ziffernfolgen — zur Prüfung markiert (Konfidenz 0,85)"),
            ("IPv4-Adresse", "Gepunktetes Vierertupel mit Oktett-Bereichsprüfung"),
            ("Kreditkartennummer", "13–19 Ziffern mit Luhn-Prüfziffer"),
        ],
        "formats": "TXT, DOCX (Word) und XLSX (Excel).",
        "not_covered": (
            "PDF wird noch nicht unterstützt, und Namen sowie Postanschriften im Fließtext "
            "werden nicht erkannt — dafür ist eine Named-Entity-Erkennung nötig, die auf der "
            "Roadmap steht. Dieses Werkzeug unterstützt deine Prüfung; es garantiert keine "
            "vollständige Anonymisierung, und du bleibst dafür verantwortlich, das Ergebnis "
            "vor der Weitergabe zu kontrollieren."
        ),
        "how_it_works": [
            (
                "Hochladen & scannen (kostenlos)",
                "Lade eine TXT-, DOCX- oder XLSX-Datei hoch und erhalte eine Fundstellenliste "
                "mit Zähler je Typ. Es fallen keine Kosten an, und es wird noch keine Datei "
                "erzeugt.",
            ),
            (
                "Fundstellen prüfen",
                "Sieh dir an, was gefunden wurde, bevor du bestätigst. Telefonnummern haben "
                "eine niedrigere Konfidenz und sind markiert, damit du entscheiden kannst.",
            ),
            (
                "Schwärzen & herunterladen (kostenpflichtig)",
                "Bestätige, um die bereinigte Datei zu erhalten — jeder Wert wird durch eine "
                "Bezeichnung ersetzt, maskiert oder entfernt. Die Ausgabe wird vor der "
                "Freigabe erneut gescannt; bleibt etwas übrig, wird keine Datei "
                "zurückgegeben (fail-closed).",
            ),
        ],
        "when": (
            "Nutze es, bevor du ein Dokument teilst oder archivierst, das Finanzdaten, "
            "Kontaktinformationen oder technische Kennzeichen enthält, die nicht nach außen "
            "dürfen — Support-Tickets mit IBANs, Testdaten-Exports mit E-Mail-Adressen, "
            "XLSX-Berichte mit internen IP-Bereichen oder Kartennummern."
        ),
        "trust": (
            "Verarbeitung auf EU-Servern ohne Dritt-KI — die Erkennung ist deterministisch "
            "(Regex + Prüfziffern), kein Sprachmodell. Deine Datei liegt nur im "
            "Arbeitsspeicher und wird direkt nach der Verarbeitung gelöscht; erkannte Werte "
            "werden nie protokolliert oder gespeichert. Die Schwärzungs-Engine ist Open "
            "Source (AGPLv3) und auditierbar."
        ),
        "legal_notice": (
            "Unterstützt beim Entfernen von PII — vor Weitergabe prüfen. Erkennt E-Mails, "
            "IBANs, Telefonnummern, IPs und Kartennummern. Erkennt keine Namen oder "
            "Anschriften. Keine Garantie vollständiger Anonymisierung."
        ),
        "faq": [
            (
                "Warum werden Namen und Adressen nicht erkannt?",
                "Strukturierte Werte wie IBANs oder Kartennummern zu erkennen ist ein "
                "Prüfziffer-Problem mit nahezu keinen Fehltreffern. Namen zu erkennen "
                "erfordert ein Sprachmodell (NER), das Falschtreffer und externe "
                "Verarbeitung mit sich bringt. Dieses Tool löst das strukturierte Problem "
                "zuverlässig; Namen/Anschriften sind ein separater, geplanter Scope — prüfe "
                "diese selbst.",
            ),
            (
                "Was bedeutet 'fail-closed'?",
                "Nach dem Schwärzen scannt die Engine die Ausgabe erneut. Ist ein geschwärzter "
                "Wert noch erkennbar, wird die Datei nicht freigegeben — du erhältst einen "
                "Fehler statt eines halb geschwärzten Dokuments. Wir blocken, statt ein "
                "unvollständiges Ergebnis auszuliefern.",
            ),
            (
                "Ist der Scan wirklich kostenlos?",
                "Ja. Eine Datei hochzuladen und die Fundstellen (Anzahl und Typen) zu sehen "
                "kostet nichts und braucht kein Konto. Das Herunterladen der geschwärzten "
                "Datei ist der kostenpflichtige Schritt — er verbraucht die monatlichen "
                "Schwärzungs-Credits deines Tarifs.",
            ),
        ],
    },
}


def get_redact_content(locale: str) -> dict:
    """Return the localized /redact content block."""
    return REDACT_CONTENT[normalize_locale(locale)]
