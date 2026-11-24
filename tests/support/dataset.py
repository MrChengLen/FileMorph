# SPDX-License-Identifier: AGPL-3.0-or-later
"""What ``element.dataset`` exposes for a page's data-* attributes.

The HTML rule: a dash before an ASCII lowercase letter is dropped and the
letter upper-cased; every other dash stays. So ``data-err-limit`` is
``dataset.errLimit``, but ``data-err-400`` is ``dataset['err-400']`` and
``dataset.err400`` is undefined — a message a script reads that way silently
comes out empty. Scripts read numbered texts with
``getAttribute('data-err-' + code)`` instead.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup


def dataset_keys(html: str) -> set[str]:
    """Every dataset key the data-* attributes of ``html`` produce."""
    keys: set[str] = set()
    for tag in BeautifulSoup(html, "html.parser").find_all(True):
        for attr in tag.attrs:
            if attr.startswith("data-"):
                keys.add(re.sub(r"-([a-z])", lambda m: m.group(1).upper(), attr[len("data-") :]))
    return keys


def dataset_reads(js: str) -> set[str]:
    """Every ``.dataset.<key>`` a script reads or writes by property name."""
    return set(re.findall(r"\.dataset\.(\w+)", js))
