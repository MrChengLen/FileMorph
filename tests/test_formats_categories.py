# SPDX-License-Identifier: AGPL-3.0-or-later
"""/formats category-bucket regression guard.

``_FORMAT_CATEGORY`` (app/api/routes/pages.py) buckets every live registry
source format for display on /formats. A source missing from the map falls
through to the catch-all "Other" bucket — which is how AVIF and EML went
missing from their proper Image/Document sections. These tests pin that
every real source has a category, so /formats renders no "Other" bucket.
"""

from __future__ import annotations

import pytest

from app.api.routes.pages import _FORMAT_CATEGORY
from app.converters.registry import get_public_conversions


def test_every_public_source_has_a_formats_category():
    uncategorized = set(get_public_conversions()) - set(_FORMAT_CATEGORY)
    assert not uncategorized, (
        f"these source formats have no _FORMAT_CATEGORY entry and fall into "
        f"the 'Other' bucket on /formats: {sorted(uncategorized)}"
    )


@pytest.mark.parametrize(
    "fmt, category",
    [("avif", "image"), ("eml", "document"), ("htm", "document")],
)
def test_known_categories(fmt, category):
    assert _FORMAT_CATEGORY.get(fmt) == category
