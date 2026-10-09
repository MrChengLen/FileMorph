# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public docs quote limits from the code — pin them so they cannot drift.

The pricing page reads ``app/core/quotas.py`` directly; the markdown docs copy
the numbers by hand, and they drifted. After the 2026-05-25 pricing overhaul
the API guide still showed the old tier table (plus a per-tier "API/min"
column, although the rate limit is per IP and the same for every tier), three
docs said anonymous uploads cap at 20 MB, and the self-hosting guide gave Pro
and Business the old concurrency caps. These tests read the numbers back out
of the markdown and compare them with the code, so the next quota change fails
CI until the docs follow.

The same goes for the status codes and error messages the docs quote: those
tests call the route and look for its answer in the markdown. And for what the
docs say about the ``pillow-heif`` wheel: those tests read the installed wheel
and ``requirements.lock``.

A "not found" failure means a sentence was reworded: check the new wording
against the code, then update the pattern here.
"""

from __future__ import annotations

import dataclasses
import importlib.metadata
import io
import json
import re
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.api.routes.auth import get_optional_user
from app.api.routes.convert import _MAX_TARGET_LEN, _download_name
from app.core.batch import BatchFileResult, build_batch_zip
from app.core.concurrency import ConcurrencyExhausted
from app.core.config import Settings
from app.core.quotas import _MB, QUOTAS
from app.main import app

DOCS = Path(__file__).resolve().parent.parent / "docs"
ROUTES = DOCS.parent / "app" / "api" / "routes"


def _text(doc: str) -> str:
    return (DOCS / doc).read_text(encoding="utf-8")


def _section(doc: str, heading: str) -> str:
    """The text under the line ``heading`` in ``docs/<doc>``, up to the next heading.

    A ``#`` line inside a fenced code block is a shell comment, not a heading."""
    text = _text(doc)
    assert f"\n{heading}\n" in text, f"{doc}: heading {heading!r} not found"
    body = text[text.index(f"\n{heading}\n") + len(heading) + 2 :]
    lines, fenced = [], False
    for line in body.split("\n"):
        if line.startswith("```"):
            fenced = not fenced
        elif line.startswith("#") and not fenced:
            break
        lines.append(line)
    return "\n".join(lines)


def _first_table(markdown: str) -> list[dict[str, str]]:
    """The first markdown table in ``markdown``, one dict per body row."""
    lines = markdown.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("|")), None)
    assert start is not None, "no markdown table under this heading"
    rows = []
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    header, _separator, *body = rows
    return [dict(zip(header, row)) for row in body]


def _mb(cell: str) -> int:
    number, unit = cell.split()
    assert unit == "MB", cell
    return int(number) * _MB


def _calls(cell: str) -> int | None:
    """``1,000`` / ``1 000`` → 1000, ``unlimited`` → None, ``n/a`` → 0 (the
    anonymous value: no account, so no monthly counter — only the per-IP rate
    limit)."""
    if cell == "unlimited":
        return None
    if cell.startswith("n/a"):
        return 0
    return int(cell.replace(",", "").replace(" ", ""))


# API-guide column → (TierQuota field, cell parser).
_GUIDE_COLUMNS = {
    "Max file size": ("max_file_size_bytes", _mb),
    "Max files / batch": ("max_files_per_batch", int),
    "Output cap": ("output_cap_bytes", _mb),
    "Concurrent requests": ("concurrency", int),
    "API calls / month": ("api_calls_per_month", _calls),
}


def test_api_guide_tier_table_matches_quotas():
    rows = _first_table(_section("api-usage-guide.md", "## Tier Quotas & Discovery"))
    # An extra column fails here on purpose. The old "API/min" column promised
    # paid tiers 60/min, but the rate limit is per client IP and per route, the
    # same for every tier (the @limiter.limit decorators on the routes).
    assert set(rows[0]) == {"Tier", *_GUIDE_COLUMNS}
    assert [row["Tier"] for row in rows] == list(QUOTAS)
    for row in rows:
        quota = QUOTAS[row["Tier"]]
        for column, (field, parse) in _GUIDE_COLUMNS.items():
            assert parse(row[column]) == getattr(quota, field), (
                f"{row['Tier']} / {column}: the doc says {row[column]!r}, "
                f"quotas.py says {getattr(quota, field)!r}"
            )


def test_api_reference_monthly_quota_table_matches_quotas():
    section = _section("api-reference.md", "### Monthly call quota (per user)")
    documented = {
        row["Tier"].lower(): _calls(row["Monthly API calls"]) for row in _first_table(section)
    }
    assert documented == {tier: q.api_calls_per_month for tier, q in QUOTAS.items()}
    # The example 429 body quotes a tier's limit as app/core/usage.py prints it.
    examples = re.findall(r"\((\d+) per month for tier '(\w+)'\)", section)
    assert examples, "api-reference.md: the example 429 body was not found"
    for limit, tier in examples:
        assert int(limit) == QUOTAS[tier].api_calls_per_month, f"429 example: {tier}"


@pytest.mark.parametrize(
    "doc, pattern",
    [
        ("api-usage-guide.md", r"\*\*(\d+) MB\*\* per file"),
        ("security-overview.md", r"Anonymous uploads cap at (\d+) MB"),
        ("vendor-security-questionnaire.md", r"Size cap, per tier\*\* — anonymous (\d+) MB"),
    ],
)
def test_docs_quote_the_anonymous_upload_cap(doc, pattern):
    text = " ".join(_text(doc).split())  # undo the markdown line wraps
    found = re.findall(pattern, text)
    assert found, f"{doc}: the anonymous size-cap sentence was not found"
    assert {int(n) * _MB for n in found} == {QUOTAS["anonymous"].max_file_size_bytes}


def test_docs_quote_the_default_request_cap():
    """``MAX_UPLOAD_SIZE_MB`` caps every whole request before any tier limit."""
    default = Settings.model_fields["max_upload_size_mb"].default
    quoted = {}
    for doc in sorted(DOCS.glob("*.md")):
        text = " ".join(doc.read_text(encoding="utf-8").split())
        found = re.findall(r"MAX_UPLOAD_SIZE_MB`? \(default:? (\d+)", text)
        if found:
            quoted[doc.name] = {int(n) for n in found}
    assert quoted, "no doc quotes the MAX_UPLOAD_SIZE_MB default any more"
    assert quoted == {name: {default} for name in quoted}


def test_self_hosting_quotes_the_per_tier_concurrency():
    text = " ".join(_text("self-hosting.md").split())
    match = re.search(
        r"anonymous and free get (\d+) concurrent request, "
        r"Pro (\d+), Business (\d+), Enterprise (\d+)",
        text,
    )
    assert match, "self-hosting.md: the per-tier concurrency sentence was not found"
    anonymous_and_free, pro, business, enterprise = map(int, match.groups())
    documented = {
        "anonymous": anonymous_and_free,
        "free": anonymous_and_free,
        "pro": pro,
        "business": business,
        "enterprise": enterprise,
    }
    assert documented == {tier: q.concurrency for tier, q in QUOTAS.items()}


_CE_LIMITS = "## Limits on a Community Edition instance"


def test_docs_quote_the_community_edition_limits():
    """Without a database every caller is anonymous, API keys included (unless
    ``API_KEYS_FILE_TIER`` says otherwise) — the docs quote those limits."""
    anonymous = QUOTAS["anonymous"]
    section = " ".join(_section("self-hosting.md", _CE_LIMITS).split())
    match = re.search(
        r"(\d+) MB per file, (\d+) file per batch, a (\d+) MB output cap "
        r"and (\d+) concurrent request per client IP",
        section,
    )
    assert match, "self-hosting.md: the Community Edition limits sentence was not found"
    size, batch, output, concurrency = map(int, match.groups())
    assert (size * _MB, batch, output * _MB, concurrency) == (
        anonymous.max_file_size_bytes,
        anonymous.max_files_per_batch,
        anonymous.output_cap_bytes,
        anonymous.concurrency,
    )
    # installation.md and the .env.example comment quote the first two.
    env_example = (DOCS.parent / ".env.example").read_text(encoding="utf-8")
    for name, text in [
        ("installation.md", _text("installation.md")),
        (".env.example", re.sub(r"\n#\s*", " ", env_example)),
    ]:
        short = re.search(r"(\d+) MB per file, (\d+) file per batch", " ".join(text.split()))
        assert short, f"{name}: the Community Edition limits sentence was not found"
        assert (int(short[1]) * _MB, int(short[2])) == (
            anonymous.max_file_size_bytes,
            anonymous.max_files_per_batch,
        ), name


def test_self_hosting_sizes_a_key_tier_by_the_code():
    """What one key-file key can take: a batch's memory and the global slots."""
    section = " ".join(_section("self-hosting.md", _CE_LIMITS).split())
    memory = re.search(r"files per batch × output cap \(`(\w+)`: (\d+) × (\d+) MB\)", section)
    assert memory, "self-hosting.md: the batch memory sentence was not found"
    quota = QUOTAS[memory[1]]
    assert (int(memory[2]), int(memory[3]) * _MB) == (
        quota.max_files_per_batch,
        quota.output_cap_bytes,
    )
    slots = re.search(
        r"`business` \((\d+)\) and `enterprise` \((\d+)\) allow more parallel requests "
        r"than the default `MAX_GLOBAL_CONCURRENCY` of (\d+)",
        section,
    )
    assert slots, "self-hosting.md: the parallel-requests sentence was not found"
    business, enterprise, global_cap = map(int, slots.groups())
    assert (business, enterprise, global_cap) == (
        QUOTAS["business"].concurrency,
        QUOTAS["enterprise"].concurrency,
        Settings.model_fields["max_global_concurrency"].default,
    )
    assert min(business, enterprise) > global_cap, "the sentence says both exceed the cap"


def test_docs_name_the_api_keys_file_tier_setting():
    default = Settings.model_fields["api_keys_file_tier"].default
    env_example = (DOCS.parent / ".env.example").read_text(encoding="utf-8")
    assert re.findall(r"^API_KEYS_FILE_TIER=(\w+)$", env_example, re.M) == [default]
    section = " ".join(_section("self-hosting.md", _CE_LIMITS).split())
    choices = re.search(r"set `API_KEYS_FILE_TIER` to ((?:`\w+`(?:, | or )?)+)", section)
    assert choices, "self-hosting.md: the list of API_KEYS_FILE_TIER values was not found"
    assert re.findall(r"`(\w+)`", choices[1]) == [tier for tier in QUOTAS if tier != default]
    # MAX_UPLOAD_SIZE_MB alone never unlocked the larger tiers on a self-host.
    guide = " ".join(_text("api-usage-guide.md").split())
    assert "raise it if the larger tier limits should apply" not in guide
    assert "`API_KEYS_FILE_TIER`" in guide


def test_api_guide_duplicate_name_example_matches_build_batch_zip():
    same = BatchFileResult(name="a.png", status="ok", size_in=1, size_out=1, content=b"x")
    zip_bytes, _summary = build_batch_zip([same] * 3, operation="convert", duration_ms=0)
    names = zipfile.ZipFile(io.BytesIO(zip_bytes)).namelist()
    assert names == ["a.png", "a_1.png", "a_2.png"]
    paragraph = _section("api-usage-guide.md", "### Duplicate filenames").strip().split("\n\n")[0]
    for name in names[1:]:
        assert f"`{name}`" in paragraph, f"the guide's duplicate-name example lacks {name}"


# ── Status codes and error messages ──────────────────────────────────────────


def _flat(doc: str) -> str:
    """``docs/<doc>`` with its line wraps undone, so a quote may span lines."""
    return " ".join(_text(doc).split())


def _with_placeholders(message: str) -> str:
    """A route's error message with its sizes written the way the guide writes them."""
    message = re.sub(r"\(\d+ MB > \d+ MB cap\)", "(N MB > M MB cap)", message)
    return re.sub(r"\(\d+ MB max for your plan\)", "(N MB max for your plan)", message)


def _upload(client, auth_headers, path: str, content: bytes, **data):
    field = "files" if path.endswith("/batch") else "file"
    files = [(field, ("a.jpg", content, "image/jpeg"))]
    return client.post(path, headers=auth_headers, files=files, data=data)


def test_api_guide_quotes_the_output_cap_messages(client, auth_headers, sample_jpg, monkeypatch):
    # A one-byte cap makes every output too large; the test key is anonymous.
    tiny = dataclasses.replace(QUOTAS["anonymous"], output_cap_bytes=1)
    monkeypatch.setitem(QUOTAS, "anonymous", tiny)
    jpg = sample_jpg.read_bytes()
    convert = _upload(client, auth_headers, "/api/v1/convert", jpg, target_format="png")
    batch = _upload(client, auth_headers, "/api/v1/convert/batch", jpg, target_formats="png")
    compress = _upload(client, auth_headers, "/api/v1/compress", jpg, quality="85")
    assert (convert.status_code, batch.status_code, compress.status_code) == (413, 422, 413)

    guide = _flat("api-usage-guide.md")
    assert "Output too large;" not in guide, "the guide still quotes the old wording"
    # A batch file's error_message is quoted in full ...
    batch_message = _with_placeholders(batch.json()["files"][0]["error_message"])
    assert f'"{batch_message}"' in guide
    # ... the single-file 413s by the sentence they share, plus /compress's hint.
    shared = "Output too large (N MB > M MB cap)."
    assert f'"{shared}"' in guide
    for response in (convert, compress):
        assert _with_placeholders(response.json()["detail"]).startswith(shared)
    compress_hint = _with_placeholders(compress.json()["detail"])[len(shared) :].strip()
    assert f'"{compress_hint}"' in guide


def test_api_guide_quotes_the_file_size_message(client, auth_headers, sample_jpg, monkeypatch):
    # A signed-in free user whose plan allows one byte per file.
    tiny = dataclasses.replace(QUOTAS["free"], max_file_size_bytes=1)
    monkeypatch.setitem(QUOTAS, "free", tiny)
    user = MagicMock()
    user.tier.value = "free"
    app.dependency_overrides[get_optional_user] = lambda: user
    try:
        r = _upload(
            client, auth_headers, "/api/v1/convert", sample_jpg.read_bytes(), target_format="png"
        )
    finally:
        app.dependency_overrides.pop(get_optional_user, None)
    assert r.status_code == 413
    assert f'"{_with_placeholders(r.json()["detail"])}"' in _flat("api-usage-guide.md")


def test_docs_quote_the_batch_length_mismatch_status(client, auth_headers, sample_jpg):
    # One file, two targets.
    r = _upload(
        client,
        auth_headers,
        "/api/v1/convert/batch",
        sample_jpg.read_bytes(),
        target_formats=["png", "png"],
    )
    assert r.status_code == 422
    layout = " ".join(_section("api-usage-guide.md", "### Multipart layout").split())
    assert f"Mismatch → `{r.status_code} " in layout
    reference = _section("api-reference.md", "### POST `/api/v1/convert/batch`")
    assert "applied to all" not in reference, "one target_formats value is not broadcast"
    # So both batch examples send one target per file.
    for section in (layout, reference):
        assert section.count('"files=@') == section.count('"target_formats=')


def test_docs_state_the_batch_target_bound():
    for doc, heading in (
        ("api-reference.md", "### POST `/api/v1/convert/batch`"),
        ("api-usage-guide.md", "### Multipart layout"),
    ):
        text = " ".join(_section(doc, heading).split())
        assert f"longer than {_MAX_TARGET_LEN} characters" in text, doc


def test_api_guide_manifest_example_matches_the_route(client, auth_headers, sample_jpg):
    # A target no converter has fails the only file: 422 with the manifest shape.
    r = _upload(
        client, auth_headers, "/api/v1/convert/batch", sample_jpg.read_bytes(), target_formats="xyz"
    )
    assert r.status_code == 422
    body = r.json()
    section = _section("api-usage-guide.md", "### Manifest schema")
    example = json.loads(section.split("```json\n", 1)[1].split("```", 1)[0])
    assert set(example["summary"]) == set(body["summary"])
    assert example["summary"]["operation"] == body["summary"]["operation"]
    # manifest.json (partial success) has the example's keys; the 422 body
    # leaves out size_out.
    ok = BatchFileResult(name="a.png", status="ok", size_in=1, size_out=1, content=b"x")
    failed = BatchFileResult(name="b.png", status="error", size_in=1, error_message="x")
    zip_bytes, _summary = build_batch_zip([ok, failed], operation="convert", duration_ms=0)
    manifest = json.loads(zipfile.ZipFile(io.BytesIO(zip_bytes)).read("manifest.json"))
    for entry in example["files"]:
        assert set(entry) == set(manifest["files"][0]), entry["name"]
        assert set(entry) - {"size_out"} == set(body["files"][0]), entry["name"]
    # Entries are named after the output: the multipart example's files and targets.
    layout = _section("api-usage-guide.md", "### Multipart layout")
    sources = re.findall(r'"files=@([^"]+)"', layout)
    targets = re.findall(r'"target_formats=([^"]+)"', layout)
    expected = [_download_name(Path(src).stem, tgt) for src, tgt in zip(sources, targets)]
    assert [entry["name"] for entry in example["files"]] == expected


def test_docs_quote_the_magic_byte_rejection(client, auth_headers):
    r = _upload(client, auth_headers, "/api/v1/convert", b"MZ" + bytes(64), target_format="png")
    assert (r.status_code, r.json()["detail"]) == (400, "File type not permitted.")
    for doc, pattern in [
        ("architecture.md", r"PHP prefixes are rejected with HTTP (\d+)"),
        ("threat-model.md", r"before any decoder runs; HTTP (\d+) returned"),
        ("api-usage-guide.md", r'Rejected with `(\d+) "File type not permitted\."`'),
    ]:
        found = re.findall(pattern, _flat(doc))
        assert found, f"{doc}: the magic-byte rejection sentence was not found"
        assert {int(code) for code in found} == {r.status_code}, doc


def test_api_guide_format_discovery_matches_the_route(client):
    section = _section("api-usage-guide.md", "## Format Discovery — `GET /api/v1/formats`")
    keys = set(client.get("/api/v1/formats").json())
    read = set(re.findall(r'formats\["(\w+)"\]', section))
    assert read, "api-usage-guide.md: the /formats example was not found"
    assert read <= keys, f"the example reads {sorted(read - keys)}; /formats has {sorted(keys)}"
    # The endpoint is free of quota, not of the rate limit.
    source = (ROUTES / "formats.py").read_text(encoding="utf-8")
    limit = re.search(r'@limiter\.limit\("(\d+)/minute"\)', source)
    assert limit, "formats.py: the @limiter.limit decorator was not found"
    quoted = re.findall(r"(\d+) requests/min per client IP", " ".join(section.split()))
    assert quoted == [limit.group(1)]


def test_self_hosting_does_not_promise_no_rate_limits():
    """The per-IP limits are route decorators, so every instance runs them."""
    why = " ".join(_section("self-hosting.md", "## Why self-host?").split())
    assert "no rate limit" not in why.lower()
    assert "`@limiter.limit(...)` decorators in `app/api/routes/*.py`" in why
    assert any("@limiter.limit(" in p.read_text(encoding="utf-8") for p in ROUTES.glob("*.py"))


def test_api_reference_retry_after_row_matches_the_code():
    rows = _first_table(_section("api-reference.md", "## Response Headers"))
    set_on = next((row["Set on"] for row in rows if row["Header"] == "`Retry-After`"), None)
    assert set_on is not None, "api-reference.md: the Retry-After header row was not found"
    # Global cap → 503, per-actor cap → 429; the monthly-quota 429 is pinned
    # in tests/test_monthly_quota.py, slowapi's header-less 429 in
    # tests/test_rate_limit.py.
    for scope in ("global", "per_actor"):
        exc = ConcurrencyExhausted(scope=scope, retry_after_seconds=5)
        assert exc.headers["Retry-After"] == "5"
        assert f"`{exc.status_code}" in set_on, f"the row leaves out {exc.status_code}"
    assert "except the rate limiter's (slowapi" in set_on


# ── Authentication ───────────────────────────────────────────────────────────

# How the docs used to say that a file route needs an API key: the per-route
# "**Authentication**: Required" line, or a sentence making X-API-Key required.
_KEY_REQUIRED = re.compile(
    r"\*\*Authentication\*\*: Required"
    r"|requires? (?:the |an? )?`?X-API-Key"
    r"|X-API-Key`? header\)? (?:is )?required",
    re.IGNORECASE,
)


def test_docs_do_not_claim_the_file_routes_need_a_key(client, sample_jpg):
    """A file route runs a request without credentials on the anonymous tier;
    only a key that is sent has to be valid. The API reference said "Required"
    on every file route, and the /docs page said all endpoints require the key."""
    files = {"file": ("a.jpg", sample_jpg.read_bytes(), "image/jpeg")}
    data = {"target_format": "png"}
    assert client.post("/api/v1/convert", files=files, data=data).status_code == 200
    r = client.post("/api/v1/convert", headers={"X-API-Key": "not-a-key"}, files=files, data=data)
    assert r.status_code == 401
    assert not _KEY_REQUIRED.search(" ".join(app.description.split())), (
        "the /docs text calls the key required"
    )
    claims = [
        f"{doc.name}: {match.group(0)!r}"
        for doc in sorted(DOCS.glob("*.md"))
        for match in _KEY_REQUIRED.finditer(" ".join(doc.read_text(encoding="utf-8").split()))
    ]
    assert not claims, f"docs say the file routes need an API key: {claims}"


# ── pillow-heif: licence and libheif ─────────────────────────────────────────


def test_licence_docs_describe_the_installed_pillow_heif_wheel():
    """pillow-heif's metadata declares BSD-3-Clause, and that is all pip-licenses
    and the release SBOM report; the GPLv2 x265 its binary wheel bundles is
    stated only in the wheel's LICENSES_bundled.txt. The docs said the metadata
    declared GPLv2 and that a scan would flag it — true up to pillow-heif 1.5.0,
    whose GPLv2 classifier 1.6.0 removed. Both facts are read back from the
    installed wheel, so an upstream change fails here instead of in a licence
    review."""
    try:
        dist = importlib.metadata.distribution("pillow-heif")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("pillow-heif not installed")
    declared = dist.metadata.get("License-Expression") or dist.metadata.get("License")
    classifiers = [
        c for c in dist.metadata.get_all("Classifier") or [] if c.startswith("License ::")
    ]
    assert (declared, classifiers) == ("BSD-3-Clause", []), (declared, classifiers)
    bundled = next((f for f in dist.files or [] if f.name == "LICENSES_bundled.txt"), None)
    assert bundled is not None, "the pillow-heif wheel no longer ships LICENSES_bundled.txt"
    notice = bundled.read_text(encoding="utf-8")
    assert "binary wheels: GPLv2" in notice
    assert re.search(r"^Name: x265\nLicense: GPLv2$", notice, re.MULTILINE), notice

    heading = "### `pillow-heif` — BSD-3-Clause metadata, GPLv2 binary wheel"
    section = " ".join(_section("third-party-licenses.md", heading).split())
    assert f"both report pillow-heif as **{declared}** and nothing else" in section
    assert "`x265` (GPL-2.0-or-later, HEVC *encode*)" in section
    assert "`LICENSES_bundled.txt`" in section
    rows = _first_table(_section("tech-stack-rationale.md", "## License Map"))
    licence = next((row["License"] for row in rows if row["Library"] == "pillow-heif"), None)
    assert licence is not None, "tech-stack-rationale.md: the pillow-heif row was not found"
    assert licence.startswith(f"{declared} (metadata)") and "`x265`" in licence, licence


_LIBHEIF_MINIMUM = re.compile(r"libheif (\d+\.\d+\.\d+) or newer")


def _prose(path: Path) -> str:
    """``path`` as one line of words, without Markdown blockquote markers or
    Dockerfile comment markers, so a sentence wrapped over several lines reads
    as it renders."""
    marker = r"^\s*#\s?" if path.name == "Dockerfile" else r"^\s*>\s?"
    lines = [re.sub(marker, "", line) for line in path.read_text(encoding="utf-8").splitlines()]
    return " ".join(" ".join(lines).split())


def test_docs_quote_the_libheif_minimum_of_the_locked_pillow_heif():
    """Built from source, pillow-heif needs a recent libheif — 1.23.1 from 1.5.0
    on, 1.23.4 from 1.8.0 on; its C source stops with an ``#error`` below it. The
    docs sent Linux users to their distribution's ``libheif-dev``, older than
    that on Debian 13 (1.19.8) until a security update. formats.md names the
    minimum with the pillow-heif version it belongs to. When requirements.lock
    moves pillow-heif, this fails until upstream's changelog has been checked
    for a new minimum and every doc quotes the same one."""
    lock = (DOCS.parent / "requirements.lock").read_text(encoding="utf-8")
    locked = re.search(r"^pillow-heif==(\S+)", lock, re.MULTILINE)
    assert locked, "requirements.lock: the pillow-heif pin was not found"
    anchor = re.search(
        r"`pillow-heif` (\d+\.\d+\.\d+), the version FileMorph pins, "
        rf"requires {_LIBHEIF_MINIMUM.pattern}",
        _prose(DOCS / "formats.md"),
    )
    assert anchor, "formats.md: the HEIC note no longer names the pinned pillow-heif"
    assert anchor.group(1) == locked.group(1), (
        f"formats.md gives the libheif minimum of pillow-heif {anchor.group(1)}, "
        f"requirements.lock pins {locked.group(1)}: check upstream's changelog for "
        "a new minimum, then update formats.md, installation.md, "
        "third-party-licenses.md and the Dockerfile comment, including what they "
        "say about Debian's libheif"
    )

    quoted: dict[str, list[str]] = {}
    for path in (*sorted(DOCS.glob("*.md")), DOCS.parent / "README.md", DOCS.parent / "Dockerfile"):
        for minimum in _LIBHEIF_MINIMUM.findall(_prose(path)):
            quoted.setdefault(minimum, []).append(path.name)
    assert set(quoted) == {anchor.group(2)}, f"the docs quote different minimums: {quoted}"
