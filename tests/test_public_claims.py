# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public claims that had drifted from the code (the October 2026 honesty pass).

Every claim stood on several surfaces at once — templates, both catalogs,
llms.txt, the JSON-LD, the content modules, README/docs, ``.env.example`` —
so each guard below covers one *kind* of claim on all of them. Fixing one
surface while another keeps the old sentence fails here.

1. Self-hosting involves no processing on the customer's behalf, so no DPA
   is needed (``docs/dpa-template.md`` §1). The pages promised a "signed DPA"
   and the pricing table ticked the DPA only for the self-hosted column (the
   row is gone; the hosted plans' DPA question is open).
2. Audit-log norms cite ISO/IEC 27001:2022 (A.8.15 …), not the 2013 numbers;
   § 39a BeurkG and the BORA/BRAO § 50 reference are gone (the latter until
   counsel confirms it), and "tamper-evident" is not translated "tamper-proof".
3. "180+ format pairs" names its document share — pinned next to the pair
   count in tests/test_format_lists_match_registry.py.
4. Target size: no "exact", no "±3 %" and no "up to 3 % above" — the target
   is an upper bound (``compress_image_to_target`` scales an image down when
   even quality 1 is too big), every surface says so, and the homepage
   comparison no longer calls target-size compression "rare".
5. Hosting: one sentence everywhere (partials/hosting_note.html) — server at
   Hetzner in the EU, connections via Cloudflare (USA), linked to privacy § 4 —
   and only where the commercial pages are on, since it describes
   filemorph.io, not a self-hosted instance. Metadata that can't carry the
   link (meta descriptions, JSON-LD, the social-preview image) says nothing
   about the hosting location.
6. /compress runs on the server, so its hero doesn't say "in your browser".
7. Pricing table (plan variant): audit log and signed releases exist for every plan.
8. No plan shows more parallel requests than the global pool runs, and the
   pages don't print the pool size; the per-minute limit is not a plan feature
   (and in the free variant the same for everyone).
9. No "live today" / "coming soon": without Stripe the pricing page says
   there are no paid plans instead of announcing ones that can't be booked.
10. Privacy policy: no "usage in your dashboard" (the dashboard has no counter).
11. Design partners: an anonymised case study, not a logo mention.
12. docs/gdpr-privacy-analysis.md: no self-service export or email change.
13. The location hint under every processing button (it replaced the homepage
    privacy note) reaches WCAG AA contrast through a design token, and no
    visible template text uses the ~1.95 : 1 grey any more.

/pricing (and the homepage teaser) has two variants: "free" (no Stripe, as on
filemorph.io) and "plans" (Stripe configured). ``every_page`` renders both;
tests about one variant switch Stripe explicitly instead of relying on the
environment the suite runs in.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from babel.messages.pofile import read_po

from app.core.config import Settings, settings
from app.core.convert_pairs import PAIR_CONTENT
from app.core.jsonld import build_site_jsonld
from app.core.templates import templates

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
TEMPLATES = ROOT / "app" / "templates"

LOCALES = ("en", "de")
PAGES = (
    "/",
    "/pricing",
    "/enterprise",
    "/compress",
    "/tools",
    "/formats",
    "/privacy",
    "/security",
    "/pdf/split",
    "/pdf/extract",
    "/pdf/compress",
    "/pdf/insert",
    *(f"/convert/{src}-to-{tgt}" for src, tgt in PAIR_CONTENT),
)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _doc(path: Path) -> str:
    """A Markdown file as one line, blockquote markers dropped."""
    return _flat(re.sub(r"^>\s?", "", path.read_text(encoding="utf-8"), flags=re.MULTILINE))


def _catalog_texts() -> dict[str, str]:
    """Every msgid and msgstr of both catalogs and the template, one entry per
    message — reading the .po as text would split a phrase at a line wrap."""
    out = {}
    for path in (*(ROOT / "locale").rglob("*.po"), ROOT / "locale" / "messages.pot"):
        with open(path, "rb") as f:
            for m in read_po(f):
                if m.id:
                    out[f"{path.relative_to(ROOT)}:{m.lineno}"] = f"{m.id} {m.string}"
    return out


def _page(client, locale: str, path: str) -> str:
    r = client.get(f"/{locale}{path}" if path != "/" else f"/{locale}/")
    assert r.status_code == 200, f"/{locale}{path} -> {r.status_code}"
    return _flat(r.text)


@pytest.fixture
def pricing_on(monkeypatch):
    """/pricing and /enterprise exist only where the commercial pages are on;
    the homepage reads the same switch from a template global set at import."""
    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    monkeypatch.setitem(templates.env.globals, "pricing_enabled", True)


@pytest.fixture
def stripe_on(monkeypatch):
    """Plans can be booked: /pricing and the homepage show the plan variant
    (cards, comparison table) instead of the free one."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")  # gitleaks:allow
    monkeypatch.setitem(templates.env.globals, "stripe_enabled", True)


@pytest.fixture
def stripe_off(monkeypatch):
    """No plan can be booked: the free variant, whatever the suite's env says."""
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    monkeypatch.setitem(templates.env.globals, "stripe_enabled", False)


@pytest.fixture(params=["stripe_off", "stripe_on"], ids=["free", "plans"])
def every_page(request, client, pricing_on):
    request.getfixturevalue(request.param)
    return {(loc, path): _page(client, loc, path) for loc in LOCALES for path in PAGES}


def _row(page: str, label: str) -> list[str]:
    """Cell texts of the table row whose first cell is ``label``."""
    match = re.search(r"<tr[^>]*><td[^>]*>" + re.escape(label) + r"</td>(.*?)</tr>", page)
    assert match, f"table row {label!r} not found"
    return [
        re.sub(r"<[^>]+>", "", cell).strip()
        for cell in re.findall(r"<td[^>]*>(.*?)</td>", match.group(1))
    ]


# ── 1. DPA ───────────────────────────────────────────────────────────────────

_DPA_PROMISE = re.compile(
    r"signed DPA|unterzeichnete[mn]? AVV|DPA template|AVV-Vorlage|Art\. 28 (?:GDPR )?DPA"
    r"|Art\. 28 AVV|updated DPA|aktualisierte AVV|Need a DPA|DPA & SLA nötig",
    re.IGNORECASE,
)


def test_no_page_promises_a_dpa_for_self_hosting(every_page):
    hits = [
        f"/{loc}{path}: {m.group(0)!r}"
        for (loc, path), page in every_page.items()
        for m in _DPA_PROMISE.finditer(page)
    ]
    assert not hits, f"a page still promises a DPA: {hits}"


def test_no_template_or_catalog_entry_promises_a_dpa():
    """Covers what the rendered pages above can't reach (gated blocks)."""
    texts = {
        str(p.relative_to(ROOT)): _flat(p.read_text(encoding="utf-8"))
        for p in TEMPLATES.rglob("*.html")
    }
    texts.update(_catalog_texts())
    hits = [
        f"{where}: {m.group(0)!r}"
        for where, text in texts.items()
        for m in _DPA_PROMISE.finditer(text)
    ]
    assert not hits, hits


@pytest.mark.parametrize(
    "path,locale,sentence",
    [
        ("/enterprise", "en", "we process no data on your behalf, so no DPA is needed"),
        (
            "/enterprise",
            "en",
            "so there is no processing on your behalf under Art. 28 GDPR and no DPA is needed.",
        ),
        ("/enterprise", "de", "keine Auftragsverarbeitung, kein AVV nötig"),
        ("/pricing", "en", "Self-hosted: no data processing on your behalf, no DPA needed"),
        ("/pricing", "de", "Selbst gehostet: keine Auftragsverarbeitung, kein AVV nötig"),
    ],
)
@pytest.mark.parametrize("variant", ["stripe_off", "stripe_on"], ids=["free", "plans"])
def test_self_hosting_pages_say_no_dpa_is_needed(
    request, client, pricing_on, variant, path, locale, sentence
):
    request.getfixturevalue(variant)
    assert sentence in _page(client, locale, path)


@pytest.mark.parametrize("locale", LOCALES)
def test_pricing_table_has_no_dpa_row(client, pricing_on, stripe_on, locale):
    """The row ticked the DPA only for the self-hosted column. Self-hosting needs
    none (its panel says so); whether a hosted plan needs one is an open legal
    question, so the table makes no DPA statement at all."""
    page = _page(client, locale, "/pricing")
    table = page[page.index("<table") : page.index("</table>")]
    assert "DPA" not in table and "AVV" not in table


def test_docs_say_self_hosting_needs_no_dpa():
    readme = _doc(ROOT / "README.md")
    licence = _doc(ROOT / "COMMERCIAL-LICENSE.md")
    questionnaire = _doc(DOCS / "vendor-security-questionnaire.md")
    onboarding = _doc(DOCS / "onboarding.md")
    assert "there is no data processing on your behalf, so no DPA is needed" in readme
    assert "involves no data processing on the customer's behalf, so no DPA" in licence
    assert "on the customer's behalf, so no DPA is needed (template §1)" in questionnaire
    assert "so there is no DPA to counter-sign" in onboarding
    for name, text in (
        ("README.md", readme),
        ("COMMERCIAL-LICENSE.md", licence),
        ("questionnaire", questionnaire),
        ("onboarding.md", onboarding),
    ):
        for phrase in (
            "(DPA, SLA",
            "a DPA, a",
            "DPA template, the",
            "signed DPA",
            "DPA + TOM + licence",
            "on our behalf",  # "Auftragsverarbeitung" is processing on *your* behalf
            "never pass through us",
            "paperwork finalised during onboarding",
            "For Compliance Edition contracts, DPA",
            "(DPA §9",
            "counter- signed DPA",
            "DPA skeleton) are the canonical",
        ):
            assert phrase not in text, f"{name} still sells a DPA: {phrase!r}"


def test_no_page_says_on_our_behalf(every_page):
    hits = [f"/{loc}{path}" for (loc, path), page in every_page.items() if "on our behalf" in page]
    assert not hits, hits


# ── 2. Audit-log norms ───────────────────────────────────────────────────────

_OLD_NORMS = re.compile(
    r"A\.12\.4|A\.9\.\d|A\.14\.2|27001:2013|ISO 27001 A\.8\.2|\bBORA\b|§ ?50 BRAO|BRAO ?§ ?50"
    r"|BeurkG|§ ?39a"
)
_TEXT_SUFFIXES = {".py", ".html", ".txt", ".md", ".po", ".pot", ".js", ".json", ".yml", ".example"}


def _repo_text_files():
    roots = [ROOT / "app", DOCS, ROOT / "locale", ROOT / "tests"]
    files = [
        p for root in roots for p in root.rglob("*") if p.is_file() and p.suffix in _TEXT_SUFFIXES
    ]
    files += [
        ROOT / name
        for name in (
            "README.md",
            "COMMERCIAL-LICENSE.md",
            "SECURITY.md",
            "CONTRIBUTING.md",
            ".env.example",
        )
    ]
    vendor = ROOT / "app" / "static" / "vendor"
    return [
        p
        for p in files
        if "__pycache__" not in p.parts
        and vendor not in p.parents
        and p != Path(__file__).resolve()
    ]


def test_no_iso_27001_2013_numbers_beurkg_or_brao_anywhere():
    """CHANGELOG.md and changelog.d/ keep the history, so they are not scanned."""
    hits = [
        f"{path.relative_to(ROOT)}: {m.group(0)!r}"
        for path in _repo_text_files()
        for m in _OLD_NORMS.finditer(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert not hits, f"outdated or unconfirmed norm references: {hits}"


def test_enterprise_cites_iso_27001_2022_for_the_audit_log(client, pricing_on):
    assert "ISO/IEC 27001:2022 control A.8.15 (logging)" in _page(client, "en", "/enterprise")
    assert "ISO/IEC 27001:2022, Maßnahme A.8.15 (Protokollierung)" in _page(
        client, "de", "/enterprise"
    )


def test_tamper_evident_is_not_translated_tamper_proof():
    catalog = " ".join(_catalog_texts().values())
    assert "anipulationssicher" not in catalog, (
        "the hash chain detects edits — it is manipulationserkennbar"
    )


# ── 4. Target size ───────────────────────────────────────────────────────────

_EXACT = re.compile(
    r"±\s?3|exact target size|exact size|exakte Zielgröße|exakte Größe|exakten Größe|Hit an exact"
    # the overshoot the compressor no longer has
    r"|up to 3 %|bis zu 3 %|5[.,]15 MB"
)


def test_no_surface_claims_an_exact_target_size(client):
    surfaces = {
        f"/{loc}{path}": _page(client, loc, path)
        for loc in LOCALES
        for path in ("/", "/formats", "/compress", "/tools")
    }
    surfaces["/llms.txt"] = client.get("/llms.txt").text
    canonical, _ = build_site_jsonld("https://files.example.com")
    surfaces["JSON-LD"] = canonical
    surfaces["README.md"] = (ROOT / "README.md").read_text(encoding="utf-8")
    hits = [
        f"{where}: {m.group(0)!r}"
        for where, text in surfaces.items()
        for m in _EXACT.finditer(text)
    ]
    assert not hits, f"the target size is an upper bound, neither exact nor exceeded: {hits}"


def test_no_catalog_entry_promises_the_overshoot():
    """The catalogs too — a stale entry would come back with the next extract."""
    hits = [text for text in _catalog_texts().values() if _EXACT.search(text)]
    assert not hits, hits


@pytest.mark.parametrize(
    "path,locale,sentence",
    [
        (
            "/",
            "en",
            "to at most a target size (for example 5 MB), so the result fits an upload limit of "
            "the same size",
        ),
        (
            "/",
            "de",
            "so komprimieren, dass sie eine Zielgröße (zum Beispiel 5 MB) nicht überschreiten — "
            "das Ergebnis passt also unter eine Upload-Grenze gleicher Größe",
        ),
        ("/", "en", "the result is at most this size"),  # the tool's target-size field
        ("/", "de", "Ergebnis höchstens so groß"),
        ("/formats", "en", "to at most a target size (for example 5 MB)"),
        (
            "/formats",
            "de",
            "so verkleinern, dass es eine Zielgröße (zum Beispiel 5 MB) nicht überschreitet",
        ),
        (
            "/compress",
            "en",
            "The size is a hard ceiling, so the result fits an upload limit of the same size.",
        ),
        (
            "/compress",
            "de",
            "Die Größe ist eine feste Obergrenze: Das Ergebnis passt also unter eine "
            "Upload-Grenze gleicher Größe.",
        ),
        ("/pdf/compress", "en", "The size is a hard ceiling: if the lowest quality"),
        ("/pdf/compress", "de", "Die Größe ist eine feste Obergrenze: Reicht die niedrigste"),
    ],
)
def test_target_size_surfaces_state_the_upper_bound(client, path, locale, sentence):
    assert sentence in _page(client, locale, path)


def test_target_size_upper_bound_matches_the_compressor(tmp_path):
    """The pages' "at most" is the compressor's own rule: an image that
    doesn't fit even at quality 1 is scaled down, not shipped above the
    target."""
    from PIL import Image

    from app.compressors.image import compress_image_to_target

    src = tmp_path / "noise.jpg"
    Image.effect_noise((800, 600), 90).convert("RGB").save(src, quality=95)
    out = tmp_path / "out.jpg"

    result = compress_image_to_target(src, out, target_bytes=20 * 1024)

    assert out.stat().st_size <= 20 * 1024
    assert result["converged"] is True
    assert result["resized_to"] is not None


@pytest.mark.parametrize(
    "locale,label,rare",
    [
        ("en", "Compress images to a target size", "rare"),
        ("de", "Bilder auf eine Zielgröße komprimieren", "selten"),
    ],
)
def test_homepage_comparison_no_longer_calls_target_size_rare(client, locale, label, rare):
    cells = _row(_page(client, locale, "/"), label)
    assert cells[0] == "✓" and rare not in cells


# ── 5. Hosting ───────────────────────────────────────────────────────────────

HOSTING = {
    "en": "Server at Hetzner in the EU, connections via Cloudflare (USA) — ",
    "de": "Server bei Hetzner in der EU, Verbindungen über Cloudflare (USA) — ",
}
_HOSTING_CLAIM = re.compile(
    r"EU[- ]hosted\b|EU-gehostet|EU[- ]Hosting|EU hosting|hosting is in the EU|Hosting liegt in der EU"
    r"|EU servers|EU-Servern|in der EU gehostet|EU-hosted infrastructure",
    re.IGNORECASE,
)


def test_no_page_has_a_bare_eu_hosting_claim(every_page):
    hits = [
        f"/{loc}{path}: {m.group(0)!r}"
        for (loc, path), page in every_page.items()
        for m in _HOSTING_CLAIM.finditer(page)
    ]
    assert not hits, f"hosting claims without Cloudflare: {hits}"


@pytest.mark.parametrize("path", ["/", "/pricing"])
@pytest.mark.parametrize("locale", LOCALES)
def test_hosting_sentence_names_cloudflare_and_links_privacy_section_4(
    client, pricing_on, path, locale
):
    page = _page(client, locale, path)
    link = re.escape(HOSTING[locale]) + rf'<a href="/{locale}/privacy#hosting"[^>]*>'
    assert re.search(link, page), f"/{locale}{path}: hosting sentence or § 4 link missing"


def test_redact_page_uses_the_hosting_sentence(client, pricing_on, monkeypatch):
    monkeypatch.setattr(settings, "ai_operations_enabled", True)
    for locale in LOCALES:
        page = _page(client, locale, "/redact")
        assert HOSTING[locale] in page and f"/{locale}/privacy#hosting" in page, locale
        assert not _HOSTING_CLAIM.search(page), locale


def test_privacy_section_4_is_the_link_target(client):
    for locale in LOCALES:
        assert '<section id="hosting"' in _page(client, locale, "/privacy"), locale


def test_llms_txt_uses_the_hosting_sentence(client, pricing_on):
    body = client.get("/llms.txt").text
    assert (
        HOSTING["en"] + f"[privacy policy § 4]({settings.app_base_url.rstrip('/')}/privacy#hosting)"
        in body
    )
    assert not _HOSTING_CLAIM.search(body)


def test_self_hosted_instance_does_not_claim_filemorph_io_hosting(client, monkeypatch):
    """Without the commercial pages (the self-host default) the homepage and
    llms.txt don't say where filemorph.io runs — the instance runs wherever its
    operator put it."""
    monkeypatch.setattr(settings, "pricing_page_enabled", False)
    monkeypatch.setitem(templates.env.globals, "pricing_enabled", False)
    for locale in LOCALES:
        page = _page(client, locale, "/")
        assert "Hetzner" not in page and "Cloudflare" not in page, locale
    body = client.get("/llms.txt").text
    assert "Hetzner" not in body and "Cloudflare" not in body


def test_privacy_redaction_section_names_the_cloudflare_transit(client, monkeypatch):
    """§ 2i said the file content is "never sent to any third party" — but the
    upload travels through Cloudflare like every request (§ 4). The server
    passes nothing on; the sentence now says both."""
    monkeypatch.setitem(templates.env.globals, "ai_operations_enabled", True)
    en, de = _page(client, "en", "/privacy"), _page(client, "de", "/privacy")
    assert "the upload and the result travel through Cloudflare" in en
    assert "laufen Upload und Ergebnis über das Netzwerk von Cloudflare" in de
    texts = {"privacy.html": _flat((TEMPLATES / "privacy.html").read_text(encoding="utf-8"))}
    texts.update(_catalog_texts())
    for where, text in texts.items():
        assert "is never sent to any third party" not in text, where
        assert "zu keinem Zeitpunkt an Dritte" not in text, where


def test_jsonld_makes_no_hosting_claim():
    """Compiled once for every deployment, self-hosters included — a hosting
    location can't be true there, and JSON-LD can't carry the § 4 link."""
    canonical, _ = build_site_jsonld("https://files.example.com")
    for word in ("EU-hosted", "Hetzner", "Cloudflare", "GDPR-friendly"):
        assert word not in canonical, word


def test_content_modules_and_docs_make_no_bare_eu_hosting_claim():
    sources = [
        ROOT / "app" / "core" / f"{name}.py"
        for name in (
            "catalog",  # page names and descriptions: llms.txt, /tools, footer
            "compress_content",
            "tools_content",
            "pdf_tools_content",
            "convert_pairs",
            "redact_content",
            "video_gif_content",
            "jsonld",
        )
    ]
    sources += [
        ROOT / "app" / "api" / "routes" / "seo.py",
        ROOT / "scripts" / "generate_og_image.py",  # og:image + JSON-LD logo, every deployment
        ROOT / "README.md",
        *sorted(DOCS.glob("*.md")),
    ]
    hits = [
        f"{p.relative_to(ROOT)}: {m.group(0)!r}"
        for p in sources
        for m in _HOSTING_CLAIM.finditer(p.read_text(encoding="utf-8"))
    ]
    assert not hits, hits


# ── 6. /compress runs on the server ──────────────────────────────────────────


def test_compress_page_does_not_claim_browser_side_processing(client):
    from app.core.compress_content import COMPRESS_CONTENT

    for locale, content in COMPRESS_CONTENT.items():
        for field in ("title", "meta", "h1", "hero", "limits"):
            assert "browser" not in content[field].lower(), (locale, field)
    summary = client.get("/llms.txt").text.split("\n## ", 1)[0]
    assert "in the browser" not in summary and "processed on the server" in summary


# ── 7. Audit log + signed releases for every plan ────────────────────────────


@pytest.mark.parametrize(
    "locale,label",
    [("en", "Audit log + signed releases"), ("de", "Audit-Log + signierte Releases")],
)
def test_pricing_table_shows_audit_log_and_signed_releases_for_every_plan(
    client, pricing_on, stripe_on, locale, label
):
    assert _row(_page(client, locale, "/pricing"), label) == ["✓", "✓", "✓", "✓"]


# ── 8. Parallel requests and the per-minute limit ────────────────────────────


def test_no_plan_shows_more_parallel_requests_than_the_global_pool(monkeypatch):
    from app.core.pricing import anonymous_plan, saas_plans

    for pool in (Settings.model_fields["max_global_concurrency"].default, 2):
        monkeypatch.setattr(settings, "max_global_concurrency", pool)
        for plan in (anonymous_plan(), *saas_plans()):
            assert plan.concurrency <= pool, (plan.tier, plan.concurrency, pool)


def test_pricing_page_explains_the_shared_pool_and_the_shared_rate_limit(
    client, pricing_on, stripe_on
):
    en, de = _page(client, "en", "/pricing"), _page(client, "de", "/pricing")
    assert "parallel slots, so no plan runs more requests at once than the server allows" in en
    assert "kein Tarif bekommt mehr gleichzeitige Anfragen, als der Server zulässt" in de
    assert "The per-minute rate limit is the same for every plan — for example 10 requests" in en
    assert "Das Minuten-Limit ist für alle Tarife gleich — zum Beispiel 10 Anfragen" in de
    # The prose doesn't print the hosted pool size (the Business column shows
    # min(6, pool), and the default is in docs/self-hosting.md, so this is
    # about not advertising it), nor the per-IP detail of the limits.
    pool = settings.max_global_concurrency
    assert f"at most {pool} requests" not in en and f"höchstens {pool} Anfragen" not in de
    for page in (en, de):
        assert (
            "req/min" not in page
            and "10 requests/minute" not in page
            and "10 Anfragen/Minute" not in page
        )


def test_free_pricing_explains_the_shared_pool_and_the_shared_rate_limit(
    client, pricing_on, stripe_off
):
    """The free variant says the same without plans: one limit for everyone."""
    en, de = _page(client, "en", "/pricing"), _page(client, "de", "/pricing")
    assert "per account (per IP address without an account)" in en
    assert "pro Konto (ohne Konto: pro IP-Adresse)" in de
    assert (
        "parallel slots, and the per-minute rate limit is the same for everyone — "
        "for example 10 requests" in en
    )
    assert (
        "parallelen Plätze des Servers, und das Minuten-Limit ist für alle gleich – "
        "zum Beispiel 10 Anfragen" in de
    )
    pool = settings.max_global_concurrency
    assert f"at most {pool} requests" not in en and f"höchstens {pool} Anfragen" not in de
    for page in (en, de):
        assert "req/min" not in page and "10 requests/minute" not in page


def test_readme_plan_table_shows_the_concurrency_an_account_can_use():
    """The table names what one request can get on the hosted server, with and
    without an account — size, batch and concurrency straight from quotas.py;
    the prose doesn't print the pool size."""
    from app.core.quotas import QUOTAS

    pool = Settings.model_fields["max_global_concurrency"].default
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for label, tier in (("Without an account", "anonymous"), ("Free account", "free")):
        row = re.search(
            rf"^\| {label} \| (\d+) MB \| (\d+) \| ([^|]+) \| (\d+) \|$", readme, re.MULTILINE
        )
        assert row, f"README table lost its {label!r} row"
        quota = QUOTAS[tier]
        calls = f"{quota.api_calls_per_month:,}" if quota.api_calls_per_month else "not metered"
        assert int(row.group(1)) == quota.max_file_size_bytes // (1024 * 1024), tier
        assert int(row.group(2)) == quota.max_files_per_batch, tier
        assert row.group(3).strip() == calls, tier
        assert int(row.group(4)) == min(quota.concurrency, pool), tier


# ── 9. No launch promises ────────────────────────────────────────────────────

_LAUNCH = re.compile(
    r"live today|launch shortly|coming soon|seit heute live|in Kürze|demnächst|Pre-launch"
    r"|Free tier is live|check back soon|not yet active|noch nicht aktiv|schau bald",
    re.IGNORECASE,
)


def test_pricing_says_there_are_no_paid_plans(client, pricing_on, monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    monkeypatch.setitem(templates.env.globals, "stripe_enabled", False)
    en, de = _page(client, "en", "/pricing"), _page(client, "de", "/pricing")
    assert "Our server costs nothing:" in en and "Unser Server kostet nichts:" in de
    assert "Will there be paid plans?" in en and "Not at the moment." in en
    assert "Wird es bezahlte Tarife geben?" in de and "Derzeit nicht." in de
    for page in (en, de):  # no plan card (the button labels also sit in FM_I18N)
        for plan_marker in ('id="pro-btn"', 'id="business-btn"', "Contact us", "Most popular"):
            assert plan_marker not in page, plan_marker
    for page in (en, de):
        assert not _LAUNCH.search(page), _LAUNCH.search(page).group(0)
    assert not _LAUNCH.search((ROOT / "README.md").read_text(encoding="utf-8"))
    assert not _LAUNCH.search(
        (ROOT / "app" / "static" / "js" / "pricing.js").read_text(encoding="utf-8")
    )
    assert "Coming Soon" not in (ROOT / ".env.example").read_text(encoding="utf-8")


# ── 10.–12. Privacy, design partners, GDPR analysis ──────────────────────────


def test_privacy_policy_does_not_promise_a_usage_view(client):
    assert "show usage in your dashboard" not in _page(client, "en", "/privacy")
    assert "Nutzung in deinem Dashboard" not in _page(client, "de", "/privacy")


def test_design_partners_give_an_anonymised_case_study(client, pricing_on):
    en, de = _page(client, "en", "/enterprise"), _page(client, "de", "/enterprise")
    assert "Anonymized case study (optional)" in en and "Anonymisierte Fallstudie (optional)" in de
    for page in (en, de):
        block = page[page.index('id="design-partner"') :]
        assert "Logo" not in block[: block.index("</section>")]


def test_gdpr_analysis_describes_the_running_service():
    text = _doc(DOCS / "gdpr-privacy-analysis.md")
    for stale in ("Export My Data", "Update your email in Settings", "dashboard export feature"):
        assert stale not in text, stale
    assert "there is no self-service export and no self-service email change" in text


# ── 13. Contrast of the location hint (formerly the homepage privacy note) ──

# Tailwind's default palette (v3.4) for the classes these notes may use; the
# ink tokens are read from tailwind.config.js so a token change is caught.
_TAILWIND_DEFAULTS = {
    "gray-950": "#030712",
    "gray-400": "#9ca3af",
    "gray-500": "#6b7280",
    "gray-600": "#4b5563",
    "gray-700": "#374151",
}


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(fg: str, bg: str) -> float:
    hi, lo = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _text_colour(classes: str) -> str:
    config = (ROOT / "tailwind.config.js").read_text(encoding="utf-8")
    ink = re.search(r"ink:\s*\{([^}]*)\}", config).group(1)
    tokens = {
        ("ink" if key == "DEFAULT" else f"ink-{key}"): value
        for key, value in re.findall(r"(\w+):\s*'(#[0-9a-fA-F]{6})'", ink)
    }
    tokens.update(_TAILWIND_DEFAULTS)
    names = [c.removeprefix("text-") for c in classes.split() if c.startswith("text-")]
    colours = [tokens[n] for n in names if n in tokens]
    assert len(colours) == 1, f"expected one text colour in {classes!r}"
    return colours[0]


def test_location_hint_meets_wcag_aa_contrast():
    """The hint sits under each processing button, inside the tool card: it has
    to read at WCAG AA on the card surface and on the page background."""
    assert 'class="h-full bg-gray-950' in (TEMPLATES / "base.html").read_text(encoding="utf-8")
    card = (TEMPLATES / "_components" / "card.html").read_text(encoding="utf-8")
    assert "bg-surface-raised" in card, "the tool card no longer uses the raised surface"
    source = (TEMPLATES / "partials" / "location_hint.html").read_text(encoding="utf-8")
    hint = re.search(r'<p class="([^"]*)" data-component="location-hint"', source)
    assert hint, "location hint not found"
    config = (ROOT / "tailwind.config.js").read_text(encoding="utf-8")
    raised = re.search(r"raised:\s*'(#[0-9a-fA-F]{6})'", config).group(1)
    for background in (_TAILWIND_DEFAULTS["gray-950"], raised):
        ratio = _contrast(_text_colour(hint.group(1)), background)
        assert ratio >= 4.5, f"{hint.group(1)!r}: {ratio:.2f} : 1 on {background} (AA: 4.5 : 1)"


def test_no_visible_template_text_uses_the_low_contrast_grey():
    """text-gray-700 on the page background is ~1.95 : 1. It may stay on
    decorative separators (aria-hidden) and in print styles only."""
    hits = []
    for path in TEMPLATES.rglob("*.html"):
        for tag in re.findall(r"<[a-zA-Z][^>]*>", path.read_text(encoding="utf-8")):
            classes = re.search(r'class="([^"]*)"', tag)
            if classes and "text-gray-700" in classes.group(1).split():
                if 'aria-hidden="true"' not in tag:
                    hits.append(f"{path.relative_to(ROOT)}: {tag[:80]}")
    assert not hits, hits
