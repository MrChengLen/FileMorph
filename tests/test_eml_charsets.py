# SPDX-License-Identifier: AGPL-3.0-or-later
"""EML → PDF: mail text is decoded in the character sets mail is written in.

Pure stdlib (``_eml_to_html``), so it runs on every host. Any charset label
outside ``_MAIL_CHARSETS`` is read as UTF-8, and labels from the mail never
reach Python's codec registry.
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


def test_a_folded_header_keeps_its_space():
    out = _eml_to_html(_mail(b"Antwort zur\r\n =?utf-8?q?K=C3=BCndigung?=", b"text/plain", b"hi"))
    assert "<td>Antwort zur Kündigung</td>" in out


def test_a_damaged_encoded_word_shows_the_header_as_it_is():
    out = _eml_to_html(_mail(b"=?utf-8?b?A?=", b"text/plain", b"hi"))
    assert "<td>=?utf-8?b?A?=</td>" in out


def test_a_header_is_read_up_to_its_limit():
    out = _eml_to_html(_mail(b"x" * 100_000, b"text/plain", b"hi"))
    assert "x" * 8192 in out
    assert "x" * 8193 not in out


def test_a_label_from_the_mail_never_reaches_the_codec_registry():
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
        assert not [name for name in seen if token in name]
        with pytest.raises(LookupError):  # the spy does see a lookup of that name
            codecs.lookup(label)
        assert [name for name in seen if token in name]
    finally:
        codecs.unregister(spy)


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
