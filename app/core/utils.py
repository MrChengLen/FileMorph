# SPDX-License-Identifier: AGPL-3.0-or-later
import unicodedata
from urllib.parse import quote

# The stem of a download whose upload name has nothing left to keep.
FALLBACK_STEM = "result"

# What a download name never carries: path separators, the characters Windows
# forbids in a name and the quote that would end the header's quoted string —
# browsers refuse them in a download name too ...
_UNSAFE_CHARS = frozenset('"*/:<>?\\|')
# ... and these Unicode categories: control and format characters (a bidi
# override makes "gnp.exe" read as "exe.png"), surrogates, private use,
# unassigned code points, and the line and paragraph separators.
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})

# What the plain filename="…" form never carries: those characters, and "%",
# which browsers may decode there.
_NOT_PLAIN = _UNSAFE_CHARS | {"%"}

# A browser sends the '"', CR and LF of a file name in a form upload as "%22",
# "%0D" and "%0A" (the HTML form encoding), which python-multipart passes on
# as they are. A name never carries any of the three.
_FORM_ESCAPES = ("%22", "%0D", "%0A")


def _unsafe(char: str) -> bool:
    """A character a download name never carries — also as a lookalike
    ("／", "？") that NFKD turns into one, as the ASCII copy in
    content_disposition would. Windows' best-fit code pages map a few more
    ("∕", "¥"); those stay, as signs of their own in a name."""
    return unicodedata.category(char) in _UNSAFE_CATEGORIES or not _UNSAFE_CHARS.isdisjoint(
        unicodedata.normalize("NFKD", char)
    )


def _clean(text: str) -> str:
    """``text`` in NFC — the decomposed "ü" of a macOS upload becomes one
    character — without the characters a download name never carries."""
    for escape in _FORM_ESCAPES:
        text = text.replace(escape, "")
    return "".join(char for char in unicodedata.normalize("NFC", text) if not _unsafe(char))


def _utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _cut(text: str, max_bytes: int) -> str:
    """The longest start of ``text`` that fits ``max_bytes`` in UTF-8."""
    return text.encode("utf-8")[:max_bytes].decode("utf-8", "ignore")


def safe_download_name(stem: str, suffix: str = "", max_bytes: int = 200) -> str:
    """Sanitise ``stem + suffix`` into the name of a download.

    The name stays the upload's: letters of every script with their accents,
    digits, spaces and punctuation are kept. Dropped are the characters in
    ``_UNSAFE_CHARS`` with their lookalikes and those in
    ``_UNSAFE_CATEGORIES`` (see ``_unsafe``), a browser's form escapes of
    them, and dots and spaces at either end. A stem of nothing but dots and
    white space becomes ``FALLBACK_STEM``, so the suffix keeps its dot.

    The name is capped at ``max_bytes`` in UTF-8, as file systems count, and
    only the stem is shortened, so the suffix a route appends (``.png``,
    ``_compressed.jpg``) survives an over-long upload name — a cut ``.pn`` is
    a file the OS can't open. Pass that suffix separately: a name pre-joined
    into ``stem`` is cut as a whole, as is a suffix that leaves no room for
    the stem. The cut runs after NFC + filtering, which both change the length.
    """
    # Each part is normalised once. Same result as cleaning the joined name:
    # route suffixes start with "." or "_", which NFC joins with nothing.
    tail = _clean(suffix)
    body = _clean(stem)
    if not body.replace(".", "").strip():
        body = FALLBACK_STEM
    name = (body + tail).strip(". ")
    if _utf8_len(name) <= max_bytes:
        return name
    tail = tail.rstrip(". ")
    if _utf8_len(tail) >= max_bytes:  # no room left for the stem: plain cut
        tail = ""
    return _cut(name, max_bytes - _utf8_len(tail)).rstrip(". ") + tail


def content_disposition(filename: str) -> str:
    """The ``Content-Disposition`` value for a download named ``filename``.

    A name in printable ASCII without "%" goes as ``filename="…"``. Any other
    carries both forms (RFC 6266, section 4.3): ``filename*=UTF-8''…``, the name
    percent-encoded (RFC 8187), which browsers and
    app/static/js/download-name.js read first, and an ASCII stand-in in
    ``filename`` for clients that read only that one (``curl -J``). The value
    is ASCII either way, so no name can break the header.
    """
    if filename.isascii() and filename.isprintable() and not _NOT_PLAIN & set(filename):
        return f'attachment; filename="{filename}"'
    return (
        f'attachment; filename="{_ascii_stand_in(filename)}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


def _ascii_stand_in(name: str) -> str:
    """``name`` for the plain form: accents dropped (é → e), and "_" for
    every other character that form can't carry and for a leading dot, which
    would hide the file ("．bashrc" decomposes to ".bashrc")."""
    stand_in = "".join(
        char if char.isascii() and char.isprintable() and char not in _NOT_PLAIN else "_"
        for char in unicodedata.normalize("NFKD", name)
        if not unicodedata.combining(char)
    )
    return "_" + stand_in[1:] if stand_in.startswith(".") else stand_in
