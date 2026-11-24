# SPDX-License-Identifier: AGPL-3.0-or-later
"""H3 — Format-registry cardinality regression guard.

The README and homepage both promise "30+ formats." If a refactor silently
drops a converter or a `@register` decorator goes stale, the public claim
breaks without a CI signal. This test pins the floor.
"""

from __future__ import annotations

from app.converters.registry import get_supported_conversions


def _all_formats() -> set[str]:
    """Return every format that appears as either a source or target."""
    m = get_supported_conversions()
    return set(m.keys()) | {tgt for tgts in m.values() for tgt in tgts}


def test_supported_conversions_count_meets_30plus_promise() -> None:
    """README + pricing copy say '30+ formats'. Pin the floor at 30."""
    assert len(_all_formats()) >= 30, (
        f"Public copy promises 30+ formats; registry has {len(_all_formats())}: {sorted(_all_formats())}"
    )
