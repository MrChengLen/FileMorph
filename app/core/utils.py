# SPDX-License-Identifier: AGPL-3.0-or-later
import re
import unicodedata


def _clean(text: str) -> str:
    return re.sub(r"[^\w\s.\-]", "", unicodedata.normalize("NFKD", text))


def safe_download_name(stem: str, suffix: str = "", max_len: int = 200) -> str:
    """Sanitise ``stem + suffix`` into a Content-Disposition filename.

    Only the stem is shortened to fit ``max_len``, so the suffix a route
    appends (``.png``, ``_compressed.jpg``) survives an over-long upload name
    — a cut ``.pn`` is a file the OS can't open. Pass that suffix separately:
    a name pre-joined into ``stem`` is cut as a whole, as is a suffix that
    leaves no room for the stem. The cut runs after NFKD + filtering, which
    both change the length.
    """
    # Each part is normalised once. Same result as cleaning the joined name:
    # route suffixes start with "." or "_", so NFKD's reordering can't cross
    # the join.
    tail = _clean(suffix)
    name = (_clean(stem) + tail).strip(". ") or "result"
    if len(name) <= max_len:
        return name
    tail = tail.rstrip(". ")
    if len(tail) >= max_len:  # no room left for the stem: plain cut
        tail = ""
    return name[: max_len - len(tail)].rstrip(". ") + tail
