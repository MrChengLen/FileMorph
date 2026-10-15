# SPDX-License-Identifier: AGPL-3.0-or-later
"""EML → PDF: mail text is decoded in the character sets mail is written in.

Pure stdlib (``_eml_to_html``), so it runs on every host. Any charset label
outside ``_MAIL_CHARSETS`` is read as UTF-8; labels are looked up in that table
only.
"""

import codecs
import uuid

import pytest

from app.converters.document import _MAIL_CHARSETS, _eml_to_html, _mail_codec


def _mail(subject: bytes, content_type: bytes, body: bytes) -> bytes:
    return (
        b"From: alice@example.com\r\nSubject: "
        + subject
        + b"\r\nMIME-Version: 1.0\r\nContent-Type: "
        + content_type
        + b"\r\nContent-Transfer-Encoding: 8bit\r\n\r\n"
        + body
    )


def test_every_mail_charset_is_a_python_codec():
    for label, codec in _MAIL_CHARSETS.items():
        assert codecs.lookup(codec).name == codec, label


@pytest.mark.parametrize(
    ("label", "codec"),
    [
        ("UTF-8", "utf-8"),
        ("US-ASCII", "cp1252"),
        (" utf8 ", "utf-8"),
        ("ISO-8859-1", "cp1252"),
        ("iso8859-1", "cp1252"),
        ("ISO_8859-15", "iso8859-15"),
        ("ISO8859-15", "iso8859-15"),
        ("iso-8859-8-i", "iso8859-8"),
        ("Windows-1252", "cp1252"),
        ("Shift_JIS", "cp932"),
        ("ks_c_5601-1987", "cp949"),
        ("GB2312", "gbk"),
        ("Big5", "cp950"),
    ],
)
def test_labels_match_the_way_mail_clients_write_them(label, codec):
    assert _mail_codec(label) == codec


@pytest.mark.parametrize("label", [None, "", "utf-7", "x-made-up", ("iso-8859-1", "", "x")])
def test_other_labels_are_read_as_utf8(label):
    assert _mail_codec(label) == "utf-8"


def test_text_in_a_mail_charset_is_decoded():
    out = _eml_to_html(
        _mail(
            b"=?iso-8859-1?q?Gr=FC=DFe?=",
            b"text/plain; charset=iso-8859-1",
            "Grüße aus Hamburg".encode("iso-8859-1"),
        )
    )
    assert "<td>Grüße</td>" in out
    assert "Grüße aus Hamburg" in out


def test_iso_8859_1_is_read_as_its_windows_superset():
    out = _eml_to_html(_mail(b"s", b"text/plain; charset=iso-8859-1", b"Preis: 10 \x80"))
    assert "Preis: 10 €" in out


def test_html_part_in_a_mail_charset_is_decoded():
    out = _eml_to_html(
        _mail(b"s", b"text/html; charset=windows-1252", "<p>Café</p>".encode("cp1252"))
    )
    assert "<p>Café</p>" in out


def test_raw_8bit_headers_are_read_as_utf8():
    out = _eml_to_html(_mail("Grüße".encode(), b"text/plain; charset=utf-8", b"hi"))
    assert "<td>Grüße</td>" in out


def test_raw_8bit_text_and_an_encoded_word_in_one_header():
    subject = "Jörg und ".encode() + b"=?utf-8?q?M=C3=BCller?="
    out = _eml_to_html(_mail(subject, b"text/plain; charset=utf-8", b"hi"))
    assert "<td>Jörg und Müller</td>" in out


@pytest.mark.parametrize(
    ("subject", "shown"),
    [
        ("Åse und Тихо ".encode() + b"=?utf-8?q?M=C3=BCller?=", "Åse und Тихо Müller"),
        (b"=?utf-8?q?M=C3?= =?utf-8?q?=BCller?=", "Müller"),  # one character over two words
        (b"=?utf-8?q?a?= =?iso-8859-1?q?b?= c", "ab c"),
        (b"=?iso-8859-1*de?q?Gr=FC=DFe?=", "Grüße"),  # with an RFC 2231 language tag
        (b"=?utf-8?b?A?= =?utf-8?q?ok?=", "=?utf-8?b?A?= ok"),  # a damaged word, then a good one
    ],
)
def test_encoded_words_as_mail_clients_write_them(subject, shown):
    out = _eml_to_html(_mail(subject, b"text/plain; charset=utf-8", b"hi"))
    assert f"<td>{shown}</td>" in out


@pytest.mark.parametrize("fold", [b"\r\n ", b"\r\n\t", b"\n ", b"\r "])
def test_a_folded_header_keeps_its_space(fold):
    out = _eml_to_html(
        _mail(b"Antwort zur" + fold + b"=?utf-8?q?K=C3=BCndigung?=", b"text/plain", b"hi")
    )
    space = fold.decode()[-1]  # the line break goes, the space or tab after it stays
    assert f"<td>Antwort zur{space}Kündigung</td>" in out


def test_a_damaged_encoded_word_is_shown_as_it_is():
    out = _eml_to_html(_mail(b"=?utf-8?b?A?=", b"text/plain", b"hi"))
    assert "<td>=?utf-8?b?A?=</td>" in out


def test_a_header_is_read_up_to_its_limit():
    out = _eml_to_html(_mail(b"x" * 100_000, b"text/plain", b"hi"))
    assert "<td>" + "x" * 8192 + " […]</td>" in out
    assert "<td>" + "x" * 8192 + "</td>" in _eml_to_html(_mail(b"x" * 8192, b"text/plain", b"hi"))


def test_labels_are_looked_up_in_the_mail_table_only():
    token = uuid.uuid4().hex
    label = f"x-made-up-{token}"
    seen: list[str] = []

    def spy(name: str):
        seen.append(name)  # and finds nothing, so lookups go on as before

    codecs.register(spy)
    try:
        # Once as an encoded word, once as a charset parameter split in two parts.
        out = _eml_to_html(
            _mail(
                f"=?{label}?q?Hallo?=".encode(),
                f'text/plain; charset*0="{label[:6]}"; charset*1="{label[6:]}"'.encode(),
                b"Hallo Welt",
            )
        )
        assert "<td>Hallo</td>" in out
        assert "Hallo Welt" in out
        # And once as the charset of a multipart boundary (RFC 2231).
        out = _eml_to_html(
            b"From: alice@example.com\r\nSubject: s\r\nMIME-Version: 1.0\r\n"
            + f"Content-Type: multipart/mixed; boundary*={label}''zz\r\n\r\n".encode()
            + b"--zz\r\nContent-Type: text/plain\r\n\r\nInside\r\n--zz--\r\n"
        )
        assert "Inside" in out
        assert not [name for name in seen if token in name]
        with pytest.raises(LookupError):  # the spy does see a lookup of that name
            codecs.lookup(label)
        assert [name for name in seen if token in name]
    finally:
        codecs.unregister(spy)


@pytest.mark.parametrize(
    "params",
    [
        "{0}*=utf-8''a; {0}*0=b",  # whole and in numbered parts (an error before Python 3.14)
        "{0}*" + "9" * 5000 + "=a",  # a section number too long to read
    ],
    ids=["whole-and-in-parts", "long-section-number"],
)
def test_malformed_parameters_are_read_as_missing(params):
    out = _eml_to_html(
        _mail(b"s", b"multipart/mixed; " + params.format("boundary").encode(), b"--a\r\n\r\nx")
    )
    assert "(no readable body)" in out
    out = _eml_to_html(
        _mail(b"s", b"text/plain; " + params.format("charset").encode(), "Grüße".encode())
    )
    assert "Grüße" in out


def _multipart(boundary: str, *parts: bytes, kind: str = "mixed") -> bytes:
    body = b"".join(b"--" + boundary.encode() + b"\r\n" + part + b"\r\n" for part in parts)
    return (
        b"From: alice@example.com\r\nSubject: s\r\nMIME-Version: 1.0\r\n"
        + f'Content-Type: multipart/{kind}; boundary="{boundary}"\r\n\r\n'.encode()
        + body
        + b"--"
        + boundary.encode()
        + b"--\r\n"
    )


def test_text_attachments_are_not_the_body():
    out = _eml_to_html(
        _multipart(
            "b",
            b"Content-Type: text/plain; charset=utf-8\r\n\r\nthe body",
            b"Content-Type: text/html; charset=utf-8\r\n"
            b'Content-Disposition: attachment; filename="page.html"\r\n\r\n<p>attached</p>',
        )
    )
    assert "the body" in out
    assert "attached" not in out


def test_an_attached_mail_is_not_the_body():
    forwarded = (
        b"Content-Type: message/rfc822\r\nContent-Disposition: attachment\r\n\r\n"
        b"From: bob@example.com\r\nSubject: inner\r\nContent-Type: text/html\r\n\r\n"
        b"<p>forwarded text</p>"
    )
    out = _eml_to_html(
        _multipart("b", b"Content-Type: text/plain; charset=utf-8\r\n\r\nmy own words", forwarded)
    )
    assert "my own words" in out
    assert "forwarded text" not in out
