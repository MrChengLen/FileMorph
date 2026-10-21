# SPDX-License-Identifier: AGPL-3.0-or-later
"""The privacy notice carries what Art. 13, 20, 21 and 77 GDPR require.

Pins, in German (the authoritative text) and in English:

1. Every data-subject right is named — Art. 15–18, 20, 21, 77 — and the
   right to object stands on its own, in a highlighted box (Art. 21(4)).
2. The complaint item names the authority responsible for the operator,
   the Hamburg commissioner, and links its website.
3. § 4 (the target of the hosting line on the homepage) says what
   Cloudflare does with a request — a US company that ends the encrypted
   connection, so files pass through it — and on what basis data goes to
   the USA.
4. The other recipients are named the way the contracts read: Zoho with
   the rare support access from India, Stripe through its Irish entity.
5. The rest of Art. 13: a legal basis for processing uploaded files,
   contact by email, a fixed log retention, whether data must be given,
   and that no automated decisions are made.
6. The German page addresses the reader as "du" throughout, and none of
   the new English sentences leaks onto it (a fuzzy or missing
   translation falls back to English silently).
7. The processor docs say what § 6 says — the pages load nothing from
   another domain — instead of "no third-party CDN", since every request
   to filemorph.io passes Cloudflare.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from jinja2.ext import babel_extract

DOCS = Path(__file__).resolve().parents[1] / "docs"
TEMPLATE = Path(__file__).resolve().parents[1] / "app" / "templates" / "privacy.html"


def _main(client, locale: str) -> BeautifulSoup:
    res = client.get(f"/{locale}/privacy")
    assert res.status_code == 200
    return BeautifulSoup(res.text, "html.parser").find("main")


def _text(node) -> str:
    return " ".join(node.get_text(" ", strip=True).split())


RIGHTS = {
    "de": [
        "Art. 15 DSGVO",
        "Art. 16 DSGVO",
        "Art. 17 DSGVO",
        "Art. 18 DSGVO",
        "Art. 20 DSGVO",
        "Art. 21 DSGVO",
        "Art. 77 DSGVO",
    ],
    "en": [
        "Art. 15 GDPR",
        "Art. 16 GDPR",
        "Art. 17 GDPR",
        "Art. 18 GDPR",
        "Art. 20 GDPR",
        "Art. 21 GDPR",
        "Art. 77 GDPR",
    ],
}
OBJECTION_HEADING = {
    "de": "Dein Widerspruchsrecht (Art. 21 DSGVO)",
    "en": "Your right to object (Art. 21 GDPR)",
}


@pytest.mark.parametrize("locale", ["de", "en"])
def test_every_right_is_named(client, locale):
    items = _text(_main(client, locale))
    missing = [r for r in RIGHTS[locale] if r not in items]
    assert not missing, missing


@pytest.mark.parametrize("locale", ["de", "en"])
def test_objection_stands_apart_in_a_highlighted_box(client, locale):
    main = _main(client, locale)
    boxes = [d for d in main.find_all("div") if "border-l-4" in d.get("class", [])]
    assert len(boxes) == 1
    box = _text(boxes[0])
    assert box.startswith(OBJECTION_HEADING[locale])
    # It covers every lit. f processing the notice names, and says how to object.
    for word in (
        ["Server-Protokolle", "Audit-Log", "Cloudflare", "privacy@filemorph.io"]
        if locale == "de"
        else ["server logs", "audit log", "Cloudflare", "privacy@filemorph.io"]
    ):
        assert word in box, word


@pytest.mark.parametrize("locale", ["de", "en"])
def test_complaint_names_the_hamburg_authority(client, locale):
    main = _main(client, locale)
    text = _text(main)
    assert "Der Hamburgische Beauftragte für Datenschutz und Informationsfreiheit" in text
    assert "Ludwig-Erhard-Straße 22" in text and "20459 Hamburg" in text
    assert main.find("a", href="https://datenschutz-hamburg.de") is not None


HOSTING_FACTS = {
    "de": [
        "Cloudflare, Inc. (San Francisco, USA)",
        "beendet Cloudflare die verschlüsselte Verbindung",
        "auch hochgeladene und umgewandelte Dateien",
        "Data Privacy Framework",
        "Art. 45 DSGVO",
        "EU-Standardvertragsklauseln",
        "Art. 6 Abs. 1 lit. f DSGVO",
        "Hetzner Online GmbH",
    ],
    "en": [
        "Cloudflare, Inc. (San Francisco, USA)",
        "Cloudflare ends the encrypted connection",
        "uploaded and converted files included",
        "Data Privacy Framework",
        "Art. 45 GDPR",
        "EU Standard Contractual Clauses",
        "Art. 6(1)(f) GDPR",
        "Hetzner Online GmbH",
    ],
}


@pytest.mark.parametrize("locale", ["de", "en"])
def test_section_4_explains_cloudflare_and_the_transfer(client, locale):
    section = _main(client, locale).find("section", id="hosting")
    assert section is not None
    text = _text(section)
    missing = [fact for fact in HOSTING_FACTS[locale] if fact not in text]
    assert not missing, missing


RECIPIENT_FACTS = {
    "de": [
        "Zoho Corporation GmbH (Deutschland)",
        "indischen Konzerngesellschaft",
        "Stripe Payments Europe, Ltd. (Dublin, Irland)",
        "in eigener Verantwortung",
        "Eine Kopie der in dieser Erklärung genannten EU-Standardvertragsklauseln",
    ],
    "en": [
        "Zoho Corporation GmbH (Germany)",
        "Indian group company",
        "Stripe Payments Europe, Ltd. (Dublin, Ireland)",
        "under their own responsibility",
        "You can get a copy of the EU Standard Contractual Clauses",
    ],
}


@pytest.mark.parametrize("locale", ["de", "en"])
def test_recipients_are_named_as_the_contracts_read(client, locale):
    text = _text(_main(client, locale))
    missing = [fact for fact in RECIPIENT_FACTS[locale] if fact not in text]
    assert not missing, missing


ARTICLE_13_REST = {
    "de": [
        # legal basis for the files themselves
        "Rechtsgrundlage: Art. 6 Abs. 1 lit. b DSGVO – wir führen die Umwandlung",
        "Wenn du uns per E-Mail schreibst",
        "spätestens nach 30 Tagen automatisch gelöscht",
        "weder gesetzlich noch vertraglich verpflichtet",
        "Automatisierte Entscheidungen im Sinne von Art. 22 DSGVO treffen wir nicht",
        "Einen Datenschutzbeauftragten haben wir nicht benannt",
        # third parties' data in a file, statutory retention, reply time
        "für personenbezogene Daten anderer Menschen in einer Datei Art. 6 Abs. 1 lit. f DSGVO",
        "verarbeiten wir nach Art. 6 Abs. 1 lit. c DSGVO",
        "spätestens innerhalb eines Monats",
        # whose notice this is, Cloudflare's challenge cookie
        "Diese Erklärung gilt für filemorph.io",
        "cf_clearance",
    ],
    "en": [
        "Legal basis: Art. 6(1)(b) GDPR — we carry out the conversion",
        "If you write to us by email",
        "deleted automatically after 30 days at the latest",
        "no legal or contractual obligation",
        "We make no automated decisions within the meaning of Art. 22 GDPR",
        "We have not appointed a data protection officer",
        "for personal data of other people in a file, Art. 6(1)(f) GDPR",
        "we process under Art. 6(1)(c) GDPR",
        "within one month at the latest",
        "This notice applies to filemorph.io",
        "cf_clearance",
    ],
}


@pytest.mark.parametrize("locale", ["de", "en"])
def test_the_rest_of_article_13_is_covered(client, locale):
    text = _text(_main(client, locale))
    missing = [fact for fact in ARTICLE_13_REST[locale] if fact not in text]
    assert not missing, missing


def test_german_text_says_du_and_has_no_english_fallback(client, redact_enabled):
    # With the redaction add-on on, so § 2i is rendered too.
    text = _text(_main(client, "de"))
    assert not re.search(r"\b(Ihr|Ihre|Ihrer|Ihren|Ihrem|Ihnen)\b", text)
    # Every longer English string of the template must be translated; a
    # missing or fuzzy entry falls back to the English msgid silently.
    with TEMPLATE.open("rb") as fh:
        msgids = [msg for _, _, msg, _ in babel_extract(fh, ["_"], [], {})]
    leaked = [msg[:60] for msg in msgids if len(msg) > 40 and msg in text]
    assert not leaked, leaked


def test_old_claims_are_gone(client):
    for locale in ("de", "en"):
        text = _text(_main(client, locale))
        # §6 used to say no external resources and no third-party CDN — but
        # every request runs through Cloudflare (§ 4).
        assert "third-party CDN" not in text and "Drittanbieter-CDN" not in text
        assert "typically up to 30 days" not in text and "typisch bis zu 30 Tage" not in text
        # § 2a: uploads do sit on disk while processed, and § 2h keeps a hash.
        assert "No file content is stored" not in text
        assert "in irgendeiner Form gespeichert" not in text
        # Cloudflare's SCCs are the fallback, not an addition to the DPF.
        assert "apply in addition" not in text and "zusätzlich gelten" not in text
    de = _text(_main(client, "de"))
    assert "Art. 6(1)" not in de  # German citation style throughout
    assert "strikt notwendig" not in de and "Barrierefreiheit" not in de


def test_processor_docs_name_the_same_entities():
    sub = (DOCS / "sub-processors.md").read_text(encoding="utf-8")
    assert "**Stripe Payments Europe, Ltd.**" in sub and "**Stripe Inc.**" not in sub
    assert "**Cloudflare, Inc.**" in sub and "Data Privacy Framework" in sub
    assert "Indian group company" in sub
    for name in ("vendor-security-questionnaire.md", "records-of-processing-template.md"):
        text = (DOCS / name).read_text(encoding="utf-8")
        assert "Stripe Payments Europe" in text, name
        assert "Indian group company" in text, name
        assert "Zoho EU, data centres in Amsterdam (NL) and Dublin (IE) |" not in text, name


def test_processor_docs_drop_the_no_cdn_claim():
    # Like § 6: the pages load nothing from another domain, but on
    # filemorph.io every request passes Cloudflare — so no "no third-party CDN".
    for name in ("sub-processors.md", "vendor-security-questionnaire.md", "dpa-tom-annex.md"):
        assert "third-party CDN" not in (DOCS / name).read_text(encoding="utf-8"), name
