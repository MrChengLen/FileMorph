# SPDX-License-Identifier: AGPL-3.0-or-later
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pikepdf
    from pypdf import PdfReader


class UnsupportedConversionError(Exception):
    def __init__(self, src: str, tgt: str):
        super().__init__(f"Conversion from '{src}' to '{tgt}' is not supported.")
        self.src = src
        self.tgt = tgt


class InvalidInputError(Exception):
    """A problem with the upload the user can fix; routes show ``str(exc)``.

    Raise it only with a message written for the user that names the fix.
    """


class EncryptedPdfError(InvalidInputError):
    """The PDF opens only with a password, and FileMorph never asks for one.

    pypdf raises ``FileNotDecryptedError`` on such a file, pikepdf
    ``PasswordError``. A PDF with only an owner password opens without one
    and never gets here. Its subclass :class:`UnsupportedPdfEncryptionError`
    covers encryption no password opens. The routes send ``error_code`` as
    ``X-FileMorph-Error-Code``.
    """

    error_code = "pdf_encrypted"
    message = (
        "This PDF is password-protected. Remove the password "
        "(e.g. open the file and print it to a new PDF) and try again."
    )

    # ``*_args``: copy and pickle re-create an exception from its args; the
    # message stays fixed either way.
    def __init__(self, *_args: object) -> None:
        super().__init__(self.message)


class UnsupportedPdfEncryptionError(EncryptedPdfError):
    """The PDF is encrypted some other way than with a password.

    With a certificate (``/Adobe.PubSec``), a DRM plug-in's own security
    handler, or a method the PDF libraries don't implement. No password
    would open it, so it gets its own code and message.
    """

    error_code = "pdf_encryption_unsupported"
    message = (
        "This PDF is protected with a certificate or an unsupported encryption. "
        "Remove the protection (e.g. ask the sender for an unprotected copy) and try again."
    )


def open_pypdf(path: Path) -> "PdfReader":
    """``pypdf.PdfReader(path)``; :class:`UnsupportedPdfEncryptionError` if
    pypdf can't handle the file's encryption.

    pypdf implements only the standard (password) security handler. Its
    constructor reads the encryption dictionary and raises
    ``NotImplementedError`` for any other handler, a ``/SubFilter``, or an
    unknown ``/V`` or crypt-filter method. Checked in pypdf 6.19: in the
    constructor that error comes only from reading the encryption
    dictionary. Later it means an unsupported stream filter instead, so only
    the constructor is guarded. A missing password shows up on the first
    object read, as ``FileNotDecryptedError``.
    """
    from pypdf import PdfReader

    try:
        return PdfReader(str(path))
    except NotImplementedError as exc:
        raise UnsupportedPdfEncryptionError() from exc


def open_pikepdf(path: Path) -> "pikepdf.Pdf":
    """``pikepdf.open(path)``, raising the errors above for an encrypted PDF
    it can't open.

    A missing password is ``PasswordError``; qpdf says the same for a
    ``/SubFilter`` or an unknown crypt-filter method under the standard
    handler. A security handler qpdf lacks (a certificate, DRM), an unknown
    ``/R`` or ``/V``, or a damaged encryption dictionary is a plain
    ``PdfError`` naming the encryption dictionary, e.g. "(encryption
    dictionary, offset 409): unsupported encryption filter"; all of them are
    refused here, before ghostscript could render the file undecrypted. Any
    other ``PdfError`` propagates unchanged.

    pikepdf is imported here, not at module load (Windows DLL load order,
    see ``app/converters/pdfa.py``).
    """
    import pikepdf

    try:
        return pikepdf.open(str(path))
    except pikepdf.PasswordError as exc:
        raise EncryptedPdfError() from exc
    except pikepdf.PdfError as exc:
        if "encryption dictionary" not in str(exc):
            raise
        raise UnsupportedPdfEncryptionError() from exc


def read_utf8_text(path: Path) -> str:
    """Decode an uploaded text file as UTF-8, or tell the user how to fix it.

    Line endings are kept as-is (the CSV readers rely on that); a leading BOM,
    as in Excel's "CSV UTF-8", is dropped. A bare ``UnicodeDecodeError`` names
    codec, byte and offset — no help to a user.
    """
    try:
        return path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidInputError(
            "The file is not UTF-8 text. Re-save it as UTF-8 (in Excel: Save As → "
            "CSV UTF-8; in text editors: Save As → Encoding) and try again."
        ) from exc


class BaseConverter(ABC):
    """Abstract base class for all file converters."""

    @abstractmethod
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        """Convert input_path and write result to output_path. Returns output_path."""
        ...
