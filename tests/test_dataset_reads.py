# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scripts read only dataset keys their page provides.

A dash before a digit stays in a dataset key (``data-err-400`` is
``dataset['err-400']``), so ``dataset.err400`` is undefined and the message a
script shows that way is empty. Twice this hid every error message: on the
contact form and in the dashboard's "Delete account" flow. Numbered texts are
read with ``getAttribute('data-err-' + code)`` (cancel.js, contact.js,
dashboard.js); every key a script does read by property name must exist.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.templates import templates
from tests.support.dataset import dataset_keys, dataset_reads

JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js"

# script → (page, needs Stripe, keys only rows built by the script carry)
PAGES = {
    "cancel.js": ("/en/cancel", True, set()),
    "contact.js": ("/en/contact", False, set()),
    "dashboard.js": ("/en/dashboard", True, {"revokeId"}),
}


@pytest.fixture
def stripe_on(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")  # gitleaks:allow
    monkeypatch.setitem(templates.env.globals, "stripe_enabled", True)


@pytest.mark.parametrize("script", sorted(PAGES))
def test_scripts_read_only_dataset_keys_their_page_provides(client, accounts_on, request, script):
    path, needs_stripe, script_built = PAGES[script]
    if needs_stripe:
        request.getfixturevalue("stripe_on")
    reads = dataset_reads((JS / script).read_text(encoding="utf-8"))
    assert reads, f"{script} reads no dataset keys — regex drift?"
    missing = reads - dataset_keys(client.get(path).text) - script_built
    assert not missing, (
        f"{script} reads dataset keys no data-* attribute on {path} produces: {missing}"
    )


@pytest.mark.parametrize(
    "script", sorted(p.name for p in JS.glob("*.js")), ids=lambda name: name.removesuffix(".js")
)
def test_no_script_reads_a_numbered_key_by_property_name(script):
    # Every own script (vendored code lives in a subfolder), so a new one is caught too.
    js = (JS / script).read_text(encoding="utf-8")
    assert not re.search(r"\.dataset\.\w*\d", js), (
        f"{script}: dataset.<name><digits> is undefined for data-<name>-<digits>; "
        "use getAttribute('data-<name>-' + code)"
    )
